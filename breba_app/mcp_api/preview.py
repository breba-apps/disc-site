"""Incremental preview publishing for the MCP push path.

``website.build_preview`` uploads every built file to the public preview bucket
on every call. The Jinja ``build`` step must still see the full filestore —
cross-file includes mean one pushed partial can change other pages' rendered
output — but MCP pushes are merge-only, so most built files come out
byte-identical to what the bucket already holds. This module mirrors
``build_preview``'s behavior while skipping those uploads: one LIST of the
product's preview prefix yields the existing ETags (the body MD5 for
single-part ``put_object`` uploads), and only files whose built bytes differ
are re-uploaded. Anything that defeats the comparison (multipart ETags,
encryption) just fails the match and re-uploads — correctness never depends on
the skip.
"""
import asyncio
import hashlib
import logging

from breba_app.builder import build
from breba_app.filesystem import FileStore
from breba_app.storage import PreviewFileStore, Settings, get_s3_client
# _inject_preview_bridge is private to website.py, but it is the single
# definition of what the preview bridge is; duplicating the injection here
# would let the MCP and browser preview paths drift.
from breba_app.website import _inject_preview_bridge

logger = logging.getLogger(__name__)


def _list_preview_etags(product_id: str, bucket=None) -> dict[str, str]:
    """ETags of the product's existing preview objects, in the target bucket.

    ``bucket`` is the same boto3 Bucket resource ``PreviewFileStore`` takes, so
    the skip decisions are made against the bucket the writes actually go to;
    ``None`` means the default public preview bucket.
    """
    bucket_name = bucket.name if bucket is not None else Settings.PUBLIC_BUCKET
    etags: dict[str, str] = {}
    paginator = get_s3_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket_name, Prefix=f"{product_id}/"):
        for obj in page.get("Contents", []):
            etags[obj["Key"]] = obj["ETag"].strip('"')
    return etags


def _render(filestore: FileStore) -> tuple[dict[str, bytes], dict[str, str], list[str]]:
    """Jinja-render the site into preview bytes plus their MD5s.

    Pure CPU and in-memory work (render, bridge-injection regexes, hashing) —
    the caller runs it in a thread so concurrent Chainlit websockets and
    ``/mcp`` requests aren't stalled for the whole pass.
    Returns ``(rendered bytes by path, md5 hex by path, failed paths)``.
    """
    built = build(filestore)
    rendered: dict[str, bytes] = {}
    md5s: dict[str, str] = {}
    failed: list[str] = []
    for path in built.list_files():
        try:
            lower = path.lower()
            if lower.endswith(".html") or lower.endswith(".htm"):
                content = _inject_preview_bridge(built.read_text(path)).encode("utf-8")
            else:
                content = built.read_bytes(path)
        except Exception:
            logger.exception("Failed to copy %r to preview; skipping", path)
            failed.append(path)
            continue
        rendered[path] = content
        md5s[path] = hashlib.md5(content).hexdigest()
    return rendered, md5s, failed


async def build_preview_incremental(product_id: str, filestore: FileStore, bucket=None) -> None:
    """Behavioral clone of ``website.build_preview`` that skips unchanged uploads."""
    # The ETag LIST and the render are independent, and both are blocking
    # (S3 I/O vs. CPU-bound Jinja/regex/MD5) — run them concurrently off the loop.
    existing, (rendered, md5s, failed) = await asyncio.gather(
        asyncio.to_thread(_list_preview_etags, product_id, bucket),
        asyncio.to_thread(_render, filestore),
    )

    target = PreviewFileStore(product_id=product_id, bucket=bucket)
    for path, content in rendered.items():
        # _make_key is private to PreviewFileStore, but it is the single
        # definition of where a preview file lands — the same key the LIST saw.
        if existing.get(target._make_key(path)) == md5s[path]:
            continue  # byte-identical to what the bucket already holds
        target.write_bytes(path, content)

    await target.flush()

    if failed:
        raise RuntimeError(f"Preview build failed for {len(failed)} file(s): {', '.join(failed)}")
