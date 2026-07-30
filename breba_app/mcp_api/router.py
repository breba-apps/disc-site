"""Headless, token-authenticated MCP push API.

Mirrors the effect of the browser ``POST /upload`` path in ``main.py`` but is
session-free: instead of an in-memory orchestrator session (``state_exists``) it
sources the product's current state from durable storage (R2/MinIO) on every call,
overlays the pushed files, and persists a new version + rebuilt preview.

Contract: push *merges* the given files onto current state and never
deletes unpushed files. Only the pushed files are written; ``batch_write`` clones
the latest version's manifest, so unpushed files are carried forward by the
manifest merge, not by re-uploading the whole snapshot. This matches the
platform-wide append/overwrite-only invariant (no single-file delete exists
anywhere). There is deliberately **no deploy endpoint**: going live stays a
site-UI-only action.

The live-session overlay relies on per-process in-memory orchestrator state
(``state_exists``/``load_state``), so it assumes a single-process deployment —
the same limitation as the browser ``/upload`` path.
"""
import asyncio
import base64
import binascii
import logging
import os

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from breba_app.filesystem.models import FileWrite
# _sanitize_path is private to versioned_r2, but it is the single source of truth
# for path rules; duplicating it here would let router and storage validation drift.
from breba_app.filesystem.versioned_r2 import NotFound, _sanitize_path
from breba_app.mcp_api import store
from breba_app.mcp_api.auth import require_push_token
from breba_app.mcp_api.preview import build_preview_incremental
from breba_app.mcp_api.products import owned_products, product_listing
from breba_app.models.product import Product
from breba_app.orchestrator import load_state, state_exists
from breba_app.storage import (
    get_active_version,
    get_index_html_path,
    list_versions,
    save_files,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


class FileIn(BaseModel):
    path: str
    content_b64: str
    # Advisory MIME type recorded in the version manifest. When omitted the
    # storage layer guesses from the extension, which stamps extensionless
    # text files (CNAME, LICENSE) as application/octet-stream — the MCP read
    # tools would then refuse to read them back as text.
    content_type: str | None = None


class PushIn(BaseModel):
    files: list[FileIn]
    # A best-effort optimistic-concurrency precondition supplied by the local
    # MCP server after it reads the active site. This deliberately guards
    # stale-agent edits without changing the product-wide storage write path.
    expected_version: int | None = None


@router.post("/push")
async def push(body: PushIn, principal: dict = Depends(require_push_token)):
    user_id, product_id = principal["user_id"], principal["product_id"]
    # Push targets a pre-existing product only; it never bootstraps one.
    if not await Product.find_one(Product.product_id == product_id):
        raise HTTPException(404, detail="Product not found; create it in the site UI first.")

    if not body.files:
        raise HTTPException(400, detail="No files to push")

    # Validate every path and decode every payload before any side effect, so one
    # bad file rejects the whole batch before anything is written anywhere. The
    # cap is read here (not at import) so tests can adjust MCP_MAX_FILE_BYTES; the
    # `or` treats a blank value (`VAR=` line in a .env) as unset, not int("").
    cap = int(os.environ.get("MCP_MAX_FILE_BYTES") or 20 * 1024 * 1024)
    decoded: list[FileWrite] = []
    for f in body.files:
        try:
            path = _sanitize_path(f.path)
        except ValueError as exc:
            raise HTTPException(400, detail=f"Invalid file path: {f.path}") from exc
        try:
            content = base64.b64decode(f.content_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(400, detail=f"Invalid base64 content for {f.path}") from exc
        if len(content) > cap:
            raise HTTPException(
                413, detail=f"{f.path} is {len(content)} bytes; the per-file cap is {cap} bytes",
            )
        decoded.append(FileWrite(path=path, content=content, content_type=f.content_type))

    # Reject edits prepared from an older snapshot rather than silently
    # overwriting a change the browser/chat agent made in the meantime. This is
    # intentionally a preflight, not a cross-process transaction: the product
    # currently treats simultaneous writers as out of scope. Unguarded pushes
    # skip the lookup entirely — no round-trip for a value that goes unused.
    active_version = None
    if body.expected_version is not None:
        active_version = await get_active_version(user_id, product_id)
        if body.expected_version != active_version:
            raise HTTPException(
                409,
                detail=(
                    f"Site changed from revision {body.expected_version} to {active_version} "
                    "since it was read. Re-read the affected files and reapply the edit before pushing."
                ),
            )

    # Durable current state; a guarded push passes the version its preflight
    # just resolved instead of re-reading the pointer.
    full_store = await store.read_all_files(user_id, product_id, active_version)
    for fw in decoded:
        full_store.write_bytes(fw.path, fw.content)

    # Persist only the pushed files: the manifest merge in batch_write carries
    # unpushed files forward, and re-saving the whole snapshot would widen the
    # window where a concurrent chat edit gets clobbered by a stale re-write.
    # Save must complete *before* the preview build starts — unlike POST /upload,
    # which runs the two concurrently: if the save failed, an already-running
    # build would publish files to the public bucket with no version recorded.
    version = await save_files(user_id, product_id, decoded)

    # A live chat session holds its own InMemoryFileStore (orchestrator._state_store),
    # loaded at chat start; without this overlay the next coder run would edit stale
    # files and persist them, silently reverting this push (POST /upload does the
    # same, before its preview build). Overlay as soon as the save is durable —
    # a preview failure below must not leave the open session poised to revert
    # an already-persisted push.
    if state_exists(user_id, product_id):
        live_store = load_state(user_id, product_id).filestore
        for fw in decoded:
            live_store.write_bytes(fw.path, fw.content)

    try:
        await build_preview_incremental(product_id, full_store)
    except Exception as e:
        # The push itself persisted; report the preview failure distinctly so
        # the client doesn't re-push the same files (stacking identical
        # versions) thinking the save failed.
        logger.exception("Preview build failed after push (version %s)", version)
        raise HTTPException(
            500,
            detail=(
                f"Files were saved as version {version}, but rebuilding the "
                f"preview failed: {e}. Do not re-push the same files; fix the "
                "reported problem and push the fix to refresh the preview."
            ),
        ) from e

    return {"version": version, "product_id": product_id}


@router.get("/versions")
async def versions(principal: dict = Depends(require_push_token)):
    user_id, product_id = principal["user_id"], principal["product_id"]
    all_versions, active = await asyncio.gather(
        list_versions(user_id, product_id),
        get_active_version(user_id, product_id),
    )
    return {"versions": all_versions, "active": active}


@router.get("/files")
async def files(version: int | None = None, principal: dict = Depends(require_push_token)):
    try:
        paths, resolved_version = await store.list_files(
            principal["user_id"], principal["product_id"], version,
        )
    except NotFound as e:
        # The message names the resolved version, so a defaulted read that hits
        # a missing manifest is reported precisely, never as "Version None".
        raise HTTPException(404, detail=str(e)) from e
    return {"files": paths, "version": resolved_version}


@router.get("/file")
async def file(path: str, version: int | None = None, principal: dict = Depends(require_push_token)):
    try:
        fw, resolved_version = await store.read_file(
            principal["user_id"], principal["product_id"], path, version,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=f"Invalid file path: {path}") from exc
    except NotFound as e:
        # read_file's message names the missing piece: the version or the path.
        raise HTTPException(404, detail=str(e)) from e
    content = fw.content.encode("utf-8") if isinstance(fw.content, str) else fw.content
    return {
        "path": path,
        "content_b64": base64.b64encode(content).decode(),
        "version": resolved_version,
    }


@router.get("/file/stat")
async def file_stat(path: str, version: int | None = None,
                    principal: dict = Depends(require_push_token)):
    """Manifest metadata for one file, so clients can refuse binary or
    oversized content before paying for the download."""
    try:
        meta = await store.stat_file(principal["user_id"], principal["product_id"], path, version)
    except ValueError as exc:
        raise HTTPException(400, detail=f"Invalid file path: {path}") from exc
    except NotFound as e:
        raise HTTPException(404, detail=str(e)) from e
    return {"path": path, **meta}


@router.get("/preview")
async def preview(principal: dict = Depends(require_push_token)):
    return {"preview_url": get_index_html_path(principal["product_id"])}


@router.get("/products")
async def products(principal: dict = Depends(require_push_token)):
    """List every product the token's user owns; ``current`` is the token's product.

    Any of the user's product-scoped tokens may call this — the list is user-level
    data the same user already sees on the consent page. It lets an MCP agent map
    a product *name* the user mentioned to the id ``switch_product`` needs.
    """
    owned = await owned_products(PydanticObjectId(principal["user_id"]))
    return {
        "products": product_listing(owned),
        "current": principal["product_id"],
    }
