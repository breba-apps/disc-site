"""Targeted version-aware reads for the MCP API.

``storage.read_all_files_in_memory`` downloads every file's bytes, which is far
more than ``/mcp/files`` (manifest metadata only) or ``/mcp/file`` (one object)
need. These helpers construct ``VersionedR2FileSystem`` directly — same pattern
as ``breba_app.storage`` — and touch only the objects actually requested.
"""
import asyncio

from botocore.exceptions import ClientError

from breba_app.filesystem import InMemoryFileStore
from breba_app.filesystem.models import FileWrite
from breba_app.filesystem.versioned_r2 import NotFound, VersionedR2FileSystem, _sanitize_path
from breba_app.storage import Settings, get_s3_client


def _filesystem(user_id: str, product_id: str) -> VersionedR2FileSystem:
    return VersionedR2FileSystem(
        bucket_name=Settings.USERS_BUCKET,
        root_prefix=f"{user_id}/{product_id}",
        s3_client=get_s3_client(),
    )


async def list_files(user_id: str, product_id: str,
                     version: int | None = None) -> tuple[list[str], int]:
    """List paths in the given version (the active one when None).

    Returns ``(paths, resolved_version)``: ``None`` is resolved here, once, so
    the version reported back is exactly the one whose manifest was listed —
    callers echoing it never re-resolve and risk disagreeing with the read.
    """
    filesystem = _filesystem(user_id, product_id)

    # VersionedR2FileSystem.list_files is synchronous S3 I/O; keep it off the event loop.
    def _sync() -> tuple[list[str], int]:
        v = filesystem.get_version() if version is None else version
        return filesystem.list_files(v), v

    return await asyncio.to_thread(_sync)


async def read_file(user_id: str, product_id: str, path: str,
                    version: int | None = None) -> tuple[FileWrite, int]:
    """Read one file from the given version (the active one when None).

    Returns ``(file, resolved_version)`` — same single-resolution contract as
    ``list_files``.
    """
    filesystem = _filesystem(user_id, product_id)
    v = version if version is not None else await asyncio.to_thread(filesystem.get_version)
    return await filesystem.read_file(path, version=v), v


async def stat_file(user_id: str, product_id: str, path: str,
                    version: int | None = None) -> dict:
    """Manifest metadata ({"size", "content_type"}) for one file — no download.

    Lets clients refuse binary or oversized files *before* fetching the bytes.
    Version 0 resolves like ``read_file``'s version-0 branch — a HEAD of the
    unversioned object — because legacy pre-versioning products keep their
    real files outside the placeholder v0 manifest. All of this metadata is
    advisory (v0 objects and pushes may carry guessed or missing types), so
    callers must keep their post-download backstops.
    """
    sanitized = _sanitize_path(path)  # validate before touching storage config
    filesystem = _filesystem(user_id, product_id)

    def _sync() -> dict:
        v = filesystem.get_version() if version is None else version
        if v == 0:
            # Mirror read_file's version-0 branch: it serves the unversioned
            # object directly, ignoring the placeholder manifest — stat must
            # agree with what a read would actually return.
            key = filesystem._prefix + "/" + sanitized
            try:
                head = filesystem._s3.head_object(Bucket=filesystem._bucket, Key=key)
            except ClientError as exc:
                raise NotFound(f"{sanitized} not found in version 0") from exc
            return {"size": head["ContentLength"],
                    "content_type": head.get("ContentType", "")}
        # _get_manifest is private; see the justification on read_all_files.
        meta = filesystem._get_manifest(v)["files"].get(sanitized)
        if not meta:
            raise NotFound(f"{sanitized} not found in version {v}")
        return {"size": meta["size"], "content_type": meta["content_type"]}

    return await asyncio.to_thread(_sync)


async def read_all_files(user_id: str, product_id: str,
                         version: int | None = None) -> InMemoryFileStore:
    """Download a version's full file set (the active one when None), entirely
    off the event loop. Callers that already resolved the active version (the
    push preflight) pass it to skip re-reading the pointer.

    ``storage.read_all_files_in_memory`` calls the synchronous ``list_files``
    (blocking S3 round-trips) directly on the event loop, and each of its
    per-file reads re-resolves the version pointer and manifest — roughly three
    round-trips per file. Here the pointer and manifest are resolved once in a
    thread and the objects are fetched concurrently by their manifest keys.
    """
    filesystem = _filesystem(user_id, product_id)

    # _get_manifest is private to VersionedR2FileSystem, but it is the single
    # source of truth for manifest layout; re-fetching and re-parsing the JSON
    # here would let the two implementations drift (same reasoning as the
    # _sanitize_path import in router.py).
    def _resolve() -> dict:
        return filesystem._get_manifest(
            filesystem.get_version() if version is None else version)

    manifest = await asyncio.to_thread(_resolve)

    s3 = get_s3_client()
    # Matches botocore's default max_pool_connections (10): get_s3_client()
    # uses the default Config, so more in-flight requests than that would
    # open throwaway connections urllib3 discards with a pool-full warning.
    sem = asyncio.Semaphore(10)

    async def _read_one(path: str, key: str) -> tuple[str, FileWrite]:
        def _get() -> FileWrite:
            obj = s3.get_object(Bucket=Settings.USERS_BUCKET, Key=key)
            return FileWrite(path, obj["Body"].read(), obj.get("ContentType"))

        async with sem:
            return path, await asyncio.to_thread(_get)

    pairs = await asyncio.gather(
        *(_read_one(path, meta["key"]) for path, meta in manifest["files"].items())
    )
    return InMemoryFileStore(dict(pairs))
