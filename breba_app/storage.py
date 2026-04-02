from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from collections import defaultdict
from pathlib import Path
from typing import TypedDict, Union

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from breba_app.config import INDEX_FILE_NAME
from breba_app.filesystem import InMemoryFileStore, FileWrite, FileStore
from breba_app.filesystem.versioned_r2 import VersionedR2FileSystem

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 1024 * 1024 * 32  # 32MB is cloud run limit

USERS_BUCKET_NAME: str = os.getenv("USERS_BUCKET")
CLOUDFLARE_ENDPOINT: str = os.getenv("CLOUDFLARE_ENDPOINT")
CDN_BASE_URL: str = os.getenv("CDN_BASE_URL") or "https://cdn.breba.app"

PUBLIC_BUCKET_NAME: str = os.getenv("PUBLIC_BUCKET")
ASSETS_PATH = "assets"

session = boto3.session.Session()
# Uses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from the environment
s3_client = session.client(
    service_name='s3',
    region_name='auto',
    endpoint_url=CLOUDFLARE_ENDPOINT,
)
s3 = session.resource("s3", endpoint_url=CLOUDFLARE_ENDPOINT)
s3_bucket = s3.Bucket(USERS_BUCKET_NAME)
public_s3_bucket = s3.Bucket(PUBLIC_BUCKET_NAME)


class FileMetadata(TypedDict):
    description: str  # No need for __description__


DirTreeValue = Union[FileMetadata, "DirTree"]
DirTree = dict[str, DirTreeValue]


class PreviewFileStore(FileStore):
    """
    Write-only FileStore that uploads preview artifacts to a public S3/R2 bucket.

    - Bucket is provided (e.g. s3.Bucket(PUBLIC_BUCKET_NAME))
    - Keys are written under: {session_id}/{path}
    - write_text() is non-blocking: it schedules an upload.
    - Call await flush() to ensure all writes finished (and raise if any failed).
    """

    def __init__(self, *, product_id: str, bucket=None):
        self._bucket = bucket or public_s3_bucket
        self._product_id = product_id.strip("/")

        self._pending: set[asyncio.Task] = set()
        self._errors: list[BaseException] = []

    def read_text(self, path: str) -> str:
        raise NotImplementedError("PreviewFileStore is write-only.")

    def list_files(self) -> list[str]:
        raise NotImplementedError("PreviewFileStore is write-only.")

    def file_exists(self, path: str) -> bool:
        raise NotImplementedError("PreviewFileStore is write-only.")

    def write_text(self, path: str, content: str) -> None:
        """
        Schedule an async upload of UTF-8 text.
        """
        content_type, encoding = mimetypes.guess_type(path)
        key = self._make_key(path)
        body = content.encode("utf-8")

        task = asyncio.create_task(
            self._put_object(
                key=key,
                body=body,
                content_type=content_type,
            )
        )
        self._track(task)

    def _make_key(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self._product_id}/{path}" if path else f"{self._product_id}/"

    def _track(self, task: asyncio.Task) -> None:
        self._pending.add(task)

        def _done(t: asyncio.Task) -> None:
            self._pending.discard(t)
            try:
                t.result()
            except BaseException as e:
                self._errors.append(e)

        task.add_done_callback(_done)

    async def _put_object(self, *, key: str, body: bytes, content_type: str | None) -> None:
        """
        boto3 is sync; run it in a thread.
        """

        def _sync_put() -> None:
            kwargs = {"Key": key, "Body": body}
            if content_type:
                kwargs["ContentType"] = content_type
            self._bucket.put_object(**kwargs)

        await asyncio.to_thread(_sync_put)

    async def flush(self) -> None:
        """
        Wait for all scheduled uploads to complete. Raises if any failed.
        """
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

        if self._errors:
            # Raise the first error; you can log/inspect the rest if needed.
            raise self._errors[0]


def public_file_url(user_name: str, session_id: str, file_name: str) -> str:
    return f"{CDN_BASE_URL}/{user_name}/{session_id}/{file_name}"


def _join_prefix(base: str) -> str:
    """Normalize a prefix to end with '/' if it is non-empty and not already ending with it."""
    if not base:
        return ""
    return base if base.endswith("/") else base + "/"

    # TODO: Delete breba-public/deployment


def _copy_one_file(source_bucket, target_bucket, source_path, target_path):
    copy_source = {"Bucket": source_bucket.name, "Key": source_path}
    target_bucket.copy(copy_source, target_path)  # blocking boto3 call
    logger.info(f"Copied {source_path} -> {target_path}")


async def _copy_files(source_bucket, target_bucket, files: list[str], target_prefix: str = None,
                      max_concurrency: int = 16):
    sem = asyncio.Semaphore(max_concurrency)

    async def _concurrency_copy(source_path: str):
        filename = source_path.split("/")[-1]
        target_path = target_prefix + filename
        async with sem:
            await asyncio.to_thread(_copy_one_file, source_bucket, target_bucket, source_path, target_path)

    tasks = [asyncio.create_task(_concurrency_copy(file_path)) for file_path in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    copied = 0
    failed = 0
    for file_path, r in zip(files, results):
        if isinstance(r, Exception):
            failed += 1
            logger.error(f"Failed to copy {file_path}: {r}")
        else:
            copied += 1

    logger.info(f"Copy complete. Copied: {copied}, Failed: {failed}")
    if failed > 0:
        raise Exception(f"Failed to copy {failed} objects.")


def _user_session_object(user_name: str, session_id: str, relative_path: str, description: str | None = None):
    key = f"{user_name}/{session_id}/{relative_path}"
    obj = s3.Object(USERS_BUCKET_NAME, key)
    if description:
        obj.metadata.update({"description": description})
    return obj


def save_image_to_private(user_name: str, session_id: str, image_name: str, content: bytes, description: str = None):
    """
    Save image bytes to private bucket. This is used for uploads of images form AI, but is not safe for user-uploaded images.
    :param user_name: username
    :param session_id: session id used for locating image files
    :param image_name: image name
    :param content: image content
    :param description: image description, stored as metadata
    """
    key = f"{user_name}/{session_id}/{ASSETS_PATH}/{image_name}"

    try:
        s3_client.put_object(
            Bucket=USERS_BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType="image/png",
            Metadata={"description": description} if description else {}
        )
        logger.info(f"Uploaded image to {USERS_BUCKET_NAME}/{key}")
    except (BotoCoreError, ClientError) as e:
        logger.error(f"Error uploading image: {e}")
        raise


def save_image_file_to_private(user_name: str, session_id: str, file_name: str, file_path: str,
                               description: str = None):
    """
    Save file to private bucket. This is used for uploads of images from user-uploaded images.
    :param user_name:
    :param session_id:
    :param file_name:
    :param file_path:
    :param description:
    :return:
    """
    key = f"{user_name}/{session_id}/{ASSETS_PATH}/{file_name}"

    file_size = Path(file_path).stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds limit of {MAX_FILE_SIZE / 1024 / 1024} MB")

    # Detect MIME type
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"  # safe fallback

    extra_args = {
        "ContentType": content_type,
    }

    if description:
        extra_args["Metadata"] = {"description": description}

    try:
        s3_client.upload_file(
            Filename=file_path,
            Bucket=USERS_BUCKET_NAME,
            Key=key,
            ExtraArgs=extra_args
        )
        logger.info(f"Uploaded file to {USERS_BUCKET_NAME}/{key}")
        return f"{CDN_BASE_URL}/{key}"
    except (BotoCoreError, ClientError) as e:
        logger.info(f"Error uploading file: {e}")
        raise


async def list_versions(user_name: str, session_id: str) -> list[int]:
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    return await asyncio.to_thread(filesystem.list_versions)


async def get_active_version(user_name: str, session_id: str) -> int:
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    return await asyncio.to_thread(filesystem.get_version)


async def set_version_active(user_name: str, session_id: str, version: int) -> None:
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    await asyncio.to_thread(filesystem.set_version, version)


async def save_spec(user_name: str, session_id: str, spec: str) -> None:
    data = spec.encode("utf-8")
    await save_file_versioned(user_name, session_id, "spec.txt", data, "text/plain")


async def save_index_html(user_name: str, session_id: str, html: str) -> None:
    data = html.encode("utf-8")
    await save_file_versioned(user_name, session_id, "index.html", data, "text/html")


async def save_files(user_name: str, session_id: str, files: list[FileWrite], version: int | None = None):
    """
    Save files to user's namespace
    :param user_name: Used to find user namespace
    :param session_id: Used to find product namespace
    :param files: files to write to system
    :param version: version to save files to, if not specified, a new version will be created
    :return: The new version number
    """
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    return await asyncio.to_thread(filesystem.batch_write, files, version)


async def read_all_files_in_memory(user_name: str, session_id: str, version: int | None = None):
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )

    file_paths = filesystem.list_files(version)

    async def read_one(file_path: str) -> tuple[str, FileWrite]:
        return file_path, await filesystem.read_file(file_path, version=version)

    path_file_pairs = await asyncio.gather(
        *(read_one(path) for path in file_paths)
    )

    return InMemoryFileStore(dict(path_file_pairs))


async def read_spec_text(user_name: str, session_id: str) -> str | None:
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    return await filesystem.read_text("spec.txt")


def get_index_html_path(product_id: str) -> str:
    return f"{get_public_url(product_id)}/index.html"


async def read_index_html(user_name: str, session_id: str) -> str:
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    return await filesystem.read_text("index.html")


async def save_file_versioned(user_name: str, session_id: str, file_name: str, content: bytes, content_type: str):
    root_prefix = f"{user_name}/{session_id}"
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=root_prefix,
        s3_client=s3_client,
    )
    await asyncio.to_thread(filesystem.write_file, file_name, content, content_type=content_type)


async def load_template(user_name: str, session_id: str, template_name: str):
    source_prefix = f"templates/{template_name}"

    def get_file_write(obj):
        resp = s3_client.get_object(Bucket=USERS_BUCKET_NAME, Key=obj["Key"])
        data = resp["Body"].read()
        ctype = resp.get("ContentType")
        # This helps maintain path relative to the source prefix
        relative_path = obj["Key"][len(source_prefix):]
        return FileWrite(path=relative_path, content=data, content_type=ctype)

    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=USERS_BUCKET_NAME, Prefix=source_prefix)
    tasks = []
    # Pagination avoids listing and iterating over all objects. Instead, we just iterate
    for page in pages:
        if "Contents" in page:
            for obj in page['Contents']:
                tasks.append(asyncio.to_thread(get_file_write, obj))

    # Need to read file contents concurrently to save time
    # cannot use copy_object because need to calculate sha for the manifest
    if len(tasks) == 0:
        raise Exception("No files found for prefix: " + source_prefix)
    files = await asyncio.gather(*tasks)

    root_prefix = f"{user_name}/{session_id}"
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=root_prefix,
        s3_client=s3_client,
    )
    return await asyncio.to_thread(filesystem.batch_write, files)


def make_dir_tree() -> DirTree:
    return defaultdict(make_dir_tree)


def register_file(parts: list[str], tree: DirTree):
    """
    Walk the tree, which generates the tree structure for all the parts. The last part is the file name so it is skipped.
    :param parts: List of path parts for a given file e.g. ["user", "session", "assets", "image.png"]
    :param tree: defaultdict generating directory tree where missing keys generate a subtree
    :return: The last node in the tree where the file needs to go
    """
    current = tree
    file_name = parts.pop()
    for part in parts:
        current = current[part]
    current[file_name] = {}
    return current[file_name]


def list_s3_structured(user_name: str, session_id: str, path: str = None) -> DirTree:
    full_prefix = f"{user_name}/{session_id}/"
    if path:
        full_prefix += f"{path}/"

    files = make_dir_tree()

    for obj_summary in s3_bucket.objects.filter(Prefix=full_prefix):
        full_key = obj_summary.key
        # You need to explicitly fetch the object to get metadata
        obj = s3_bucket.Object(full_key)
        obj_metadata = obj.metadata
        description = obj_metadata.get("description", "No description")

        relative_path = full_key[len(full_prefix):]
        parts = relative_path.split("/")
        file = register_file(parts, files)
        file["__description__"] = description

    return files


def format_tree(tree: DirTree, indent=0) -> list[str]:
    lines = []
    for key, value in sorted(tree.items()):
        if isinstance(value, dict) and "__description__" in value:
            desc = value["__description__"]
            lines.append("  " * indent + f"- {key} ({desc})")
        else:
            lines.append("  " * indent + f"{key}/")
            lines.extend(format_tree(value, indent + 1))
    return lines


async def list_file_assets(user_name: str, session_id: str) -> str:
    dir_tree = await asyncio.to_thread(list_s3_structured, user_name, session_id, ASSETS_PATH)
    dir_url = public_file_url(user_name, session_id, ASSETS_PATH)
    file_list = "\n".join(format_tree(dir_tree))
    return f"{dir_url} contains the following files:\n{file_list}"


def get_public_url(site_name: str) -> str:
    return f"https://{site_name}.breba.site"


async def upload_site(user_name: str, session_id: str, site_name: str):
    """
    Uploads site to google cloud
    Example: upload_site("/Users/yason/breba/disc-site/sites/test-site", "test-site")
    :param user_name: username
    :param session_id: session id used for locating site files
    :param site_name: site name where all the files will be stored
    :return: public url of deployed site
    """
    # TODO: convert to async because GCP is a blocking call, we don't want to have to wait
    # TODO: when empty dir is being uploaded, should pass back an error message
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )

    # Need to get full path to files, because we are copying across buckets
    files = filesystem.list_files(absolute=True)

    await _copy_files(s3_bucket, public_s3_bucket, files, site_name + "/")

    return get_public_url(site_name)


async def upload_preview(user_name: str, session_id: str, file: FileWrite):
    """
    Uploads site to google cloud
    Example: upload_site("/Users/yason/breba/disc-site/sites/test-site", "test-site")
    :param user_name: username
    :param session_id: session id used for locating site files
    :return: public url of deployed site
    """
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )

    # TODO: public_s3_bucket.write(file)

    return get_public_url(session_id)


async def delete_uploaded_sites(site_names: list[str]):
    keys = []
    # Collect all the files for all the sites
    for site_name in site_names:
        prefix = f"{site_name}/"
        # We are not planning to have more than 100 files for a while
        list_kwargs = {
            "Bucket": PUBLIC_BUCKET_NAME,
            "Prefix": prefix,
            "MaxKeys": 100,
        }

        list_response = s3_client.list_objects_v2(**list_kwargs)

        if not list_response.get("Contents"):
            break

        keys += [{"Key": obj["Key"]} for obj in list_response["Contents"]]

    if keys:
        s3_client.delete_objects(
            Bucket=PUBLIC_BUCKET_NAME,
            Delete={"Objects": keys, "Quiet": True}
        )


async def has_cloud_storage(user_name: str, session_id: str):
    filesystem = VersionedR2FileSystem(
        bucket_name=USERS_BUCKET_NAME,
        root_prefix=f"{user_name}/{session_id}",
        s3_client=s3_client,
    )
    return filesystem.file_exists(INDEX_FILE_NAME)


async def delete_product_files(user_name: str, session_id: str) -> int:
    prefix = f"{user_name}/{session_id}/"
    deleted_total = 0

    def _bulk_delete_prefix() -> int:
        nonlocal deleted_total
        continuation_token = None

        while True:
            list_kwargs = {
                "Bucket": USERS_BUCKET_NAME,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if continuation_token:
                list_kwargs["ContinuationToken"] = continuation_token

            list_response = s3_client.list_objects_v2(**list_kwargs)

            if not list_response.get("Contents"):
                break

            keys = [{"Key": obj["Key"]} for obj in list_response["Contents"]]

            delete_response = s3_client.delete_objects(
                Bucket=USERS_BUCKET_NAME,
                Delete={"Objects": keys, "Quiet": True}
            )

            deleted_this_batch = len(keys)
            deleted_total += deleted_this_batch
            logger.info("Deleted %d objects (prefix: %s)", deleted_this_batch, prefix)

            # Handle partial failures
            if delete_response.get("Errors"):
                for err in delete_response["Errors"]:
                    logger.warning("Failed to delete %s: %s", err["Key"], err["Code"])

            # Continue paginating
            if not list_response.get("IsTruncated"):
                break
            continuation_token = list_response.get("NextContinuationToken")

        return deleted_total

    try:
        return await asyncio.to_thread(_bulk_delete_prefix)
    except Exception as e:
        logger.error("Failed to delete product %s/%s: %s", user_name, session_id, e)
        raise
