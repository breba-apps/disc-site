#!/usr/bin/env python3
"""
Migrate R2 storage namespace from {username}/{product_id}/... to {user_id}/{product_id}/...

Run steps in order. All steps default to dry-run; pass --execute to apply.

  Step 1 — copy R2 objects (USERS_BUCKET)
    Server-side copy every object from {username}/{product_id}/...
    to {user_id}/{product_id}/... Original keys are left in place.

    uv run python migrations/migrate_to_user_id_namespace.py --step 1
    uv run python migrations/migrate_to_user_id_namespace.py --step 1 --execute
    uv run python migrations/migrate_to_user_id_namespace.py --step 1 --user alice@example.com --execute

  Step 2 — rewrite HTML in USERS_BUCKET
    Rewrite CDN asset URLs in HTML files at the new {user_id}/... keys so
    references to {cdn_base}/{username}/... become {cdn_base}/{user_id}/...
    Step 1 must have completed before running this.

    uv run python migrations/migrate_to_user_id_namespace.py --step 2
    uv run python migrations/migrate_to_user_id_namespace.py --step 2 --execute
    uv run python migrations/migrate_to_user_id_namespace.py --step 2 --user alice@example.com --execute

  Step 3 — rewrite HTML in PUBLIC_BUCKET (optional)
    Deployed sites live at {deployment_id}/... in PUBLIC_BUCKET. Keys don't
    contain username, but HTML content may reference old CDN asset URLs.
    This step rewrites those URLs in-place.

    Skip this step if you prefer to fix public sites by redeploying them
    through the app — that will push fresh HTML with correct URLs.

    uv run python migrations/migrate_to_user_id_namespace.py --step 3
    uv run python migrations/migrate_to_user_id_namespace.py --step 3 --execute
    uv run python migrations/migrate_to_user_id_namespace.py --step 3 --user alice@example.com --execute
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bson import DBRef

from breba_app.config import load_env, init_db
from breba_app.models.deployment import Deployment
from breba_app.models.product import Product
from breba_app.models.user import User
from breba_app.storage import Settings, get_s3_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _list_objects(s3, bucket: str, prefix: str) -> list[dict]:
    objects = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects.extend(page.get("Contents", []))
    return objects


# ---------------------------------------------------------------------------
# Step 1: copy objects in USERS_BUCKET
# ---------------------------------------------------------------------------

def _copy_object(s3, bucket: str, src_key: str, dst_key: str) -> None:
    s3.copy_object(
        CopySource={"Bucket": bucket, "Key": src_key},
        Bucket=bucket,
        Key=dst_key,
    )


def step1_copy_user_objects(
    s3, bucket: str,
    username: str, user_id: str, product_id: str,
    execute: bool,
) -> int:
    """Server-side copy {username}/{product_id}/... → {user_id}/{product_id}/...
    Returns number of objects copied."""
    src_prefix = f"{username}/{product_id}/"
    dst_prefix = f"{user_id}/{product_id}/"

    objects = _list_objects(s3, bucket, src_prefix)
    if not objects:
        log.info("  %s — no objects found", src_prefix)
        return 0

    for obj in objects:
        src_key = obj["Key"]
        rel_path = src_key[len(src_prefix):]
        dst_key = dst_prefix + rel_path
        log.info("  copy  %s  ->  %s", src_key, dst_key)
        if execute:
            _copy_object(s3, bucket, src_key, dst_key)

    return len(objects)


# ---------------------------------------------------------------------------
# Step 2: rewrite CDN URLs in HTML
# ---------------------------------------------------------------------------

def _rewrite_object_html(
    s3, bucket: str, key: str,
    old_url: str, new_url: str,
    execute: bool,
) -> bool:
    """Read HTML at key, rewrite CDN URLs, write back. Returns True if content changed."""
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    content_type = response.get("ContentType", "text/html")

    new_content = content.replace(old_url, new_url)
    if new_content == content:
        return False

    if execute:
        s3.put_object(Bucket=bucket, Key=key, Body=new_content.encode("utf-8"), ContentType=content_type)
    return True


def step2_rewrite_users_bucket_html(
    s3, bucket: str, cdn_base: str,
    username: str, user_id: str, product_id: str,
    execute: bool,
) -> int:
    """Rewrite CDN URLs in HTML at the already-copied {user_id}/{product_id}/... keys.
    Returns number of HTML files rewritten."""
    # Only look at the new (user_id) prefix — step 1 must have run first.
    prefix = f"{user_id}/{product_id}/"
    old_url = f"{cdn_base}/{username}/{product_id}/"
    new_url = f"{cdn_base}/{user_id}/{product_id}/"

    objects = _list_objects(s3, bucket, prefix)
    rewritten = 0
    for obj in objects:
        key = obj["Key"]
        if not key.endswith(".html"):
            continue
        changed = _rewrite_object_html(s3, bucket, key, old_url, new_url, execute)
        status = "rewritten" if changed else "no change"
        log.info("  [users-bucket] %s  %s", key, status)
        if changed:
            rewritten += 1

    return rewritten


def step2_rewrite_public_bucket_html(
    s3, bucket: str, cdn_base: str,
    username: str, user_id: str, deployment_ids: list[str],
    execute: bool,
) -> int:
    """Rewrite CDN URLs in deployed HTML files in PUBLIC_BUCKET.
    Keys are {deployment_id}/... (no username in key, only in content).
    Returns number of HTML files rewritten."""
    old_url = f"{cdn_base}/{username}/"
    new_url = f"{cdn_base}/{user_id}/"

    rewritten = 0
    for deployment_id in deployment_ids:
        objects = _list_objects(s3, bucket, f"{deployment_id}/")
        for obj in objects:
            key = obj["Key"]
            if not key.endswith(".html"):
                continue
            changed = _rewrite_object_html(s3, bucket, key, old_url, new_url, execute)
            status = "rewritten" if changed else "no change"
            log.info("  [public-bucket] %s  %s", key, status)
            if changed:
                rewritten += 1

    return rewritten


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def _load_user_data(username_filter: str | None) -> list[tuple]:
    """Return list of (user, products, deployment_ids)."""
    query = User.find(User.username == username_filter) if username_filter else User.find()
    users = await query.to_list()
    result = []
    for user in users:
        products = await Product.find(Product.user.id == user.id).to_list()
        deployments = []
        for product in products:
            deps = await Deployment.find(
                Deployment.product == DBRef("products", product.id)
            ).to_list()
            deployments.extend(deps)
        deployment_ids = [d.deployment_id for d in deployments]
        result.append((user, products, deployment_ids))
    return result


async def run_step1(username_filter: str | None, execute: bool) -> None:
    load_env()
    await init_db()

    s3 = get_s3_client()
    bucket = Settings.USERS_BUCKET

    if not execute:
        log.info("=== DRY-RUN — pass --execute to apply ===")

    rows = await _load_user_data(username_filter)
    log.info("Step 1: copying objects for %d user(s)", len(rows))

    total = 0
    for user, products, _ in rows:
        user_id = str(user.id)
        log.info("[%s] -> user_id=%s  products=%d", user.username, user_id, len(products))
        for product in products:
            try:
                n = step1_copy_user_objects(s3, bucket, user.username, user_id, product.product_id, execute)
                total += n
            except Exception:
                log.exception("  failed for product %s", product.product_id)

    log.info("=== Step 1 complete. objects=%d ===", total)


async def run_step2(username_filter: str | None, execute: bool) -> None:
    load_env()
    await init_db()

    s3 = get_s3_client()
    bucket = Settings.USERS_BUCKET
    cdn_base = Settings.CDN_BASE_URL.rstrip("/")

    if not execute:
        log.info("=== DRY-RUN — pass --execute to apply ===")

    rows = await _load_user_data(username_filter)
    log.info("Step 2: rewriting HTML in USERS_BUCKET for %d user(s)", len(rows))

    total = 0
    for user, products, _ in rows:
        user_id = str(user.id)
        log.info("[%s] -> user_id=%s  products=%d", user.username, user_id, len(products))

        for product in products:
            try:
                n = step2_rewrite_users_bucket_html(
                    s3, bucket, cdn_base,
                    user.username, user_id, product.product_id, execute,
                )
                total += n
            except Exception:
                log.exception("  failed for product %s", product.product_id)

    log.info("=== Step 2 complete. html_files_rewritten=%d ===", total)


async def run_step3(username_filter: str | None, execute: bool) -> None:
    load_env()
    await init_db()

    s3 = get_s3_client()
    bucket = Settings.PUBLIC_BUCKET
    cdn_base = Settings.CDN_BASE_URL.rstrip("/")

    if not execute:
        log.info("=== DRY-RUN — pass --execute to apply ===")

    rows = await _load_user_data(username_filter)
    log.info("Step 3: rewriting HTML in PUBLIC_BUCKET for %d user(s)", len(rows))

    total = 0
    for user, _, deployment_ids in rows:
        user_id = str(user.id)
        if not deployment_ids:
            log.info("[%s] no deployments, skipping", user.username)
            continue
        log.info("[%s] -> user_id=%s  deployments=%d", user.username, user_id, len(deployment_ids))
        try:
            n = step2_rewrite_public_bucket_html(
                s3, bucket, cdn_base,
                user.username, user_id, deployment_ids, execute,
            )
            total += n
        except Exception:
            log.exception("  failed for %s", user.username)

    log.info("=== Step 3 complete. html_files_rewritten=%d ===", total)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate R2 namespace from username to user_id"
    )
    parser.add_argument(
        "--step", type=int, choices=[1, 2, 3], required=True,
        help="1 = copy R2 objects, 2 = rewrite HTML in USERS_BUCKET, 3 = rewrite HTML in PUBLIC_BUCKET (optional)",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Apply changes (default is dry-run)",
    )
    parser.add_argument(
        "--user", metavar="USERNAME",
        help="Migrate only this username (useful for testing one account first)",
    )
    args = parser.parse_args()

    if args.step == 1:
        asyncio.run(run_step1(args.user, args.execute))
    elif args.step == 2:
        asyncio.run(run_step2(args.user, args.execute))
    else:
        asyncio.run(run_step3(args.user, args.execute))


if __name__ == "__main__":
    main()
