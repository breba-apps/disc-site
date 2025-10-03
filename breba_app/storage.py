from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Tuple, TypedDict, Union

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 1024 * 1024 * 32  # 32MB is cloud run limit

USERS_BUCKET_NAME: str = os.getenv("USERS_BUCKET")
CLOUDFLARE_ENDPOINT: str = os.getenv("CLOUDFLARE_ENDPOINT")
CDN_BASE_URL: str = os.getenv("CDN_BASE_URL") or "https://cdn.breba.app"

session = boto3.session.Session()
# Uses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from the environment
s3_client = session.client(
    service_name='s3',
    region_name='auto',
    endpoint_url=CLOUDFLARE_ENDPOINT,
)
s3 = session.resource("s3", endpoint_url=CLOUDFLARE_ENDPOINT)
s3_bucket = s3.Bucket(USERS_BUCKET_NAME)
public_s3_bucket = s3.Bucket(os.getenv("PUBLIC_BUCKET"))


class FileMetadata(TypedDict):
    description: str  # No need for __description__


DirTreeValue = Union[FileMetadata, "DirTree"]
DirTree = dict[str, DirTreeValue]


def public_file_url(user_name: str, session_id: str, file_name: str) -> str:
    return f"{CDN_BASE_URL}/{user_name}/{session_id}/{file_name}"


def _copy_directory_s3(source_bucket, target_bucket, prefix: str, target_prefix: str = None):
    try:
        # TODO: optimize this using asyncio.to_thread or create_task
        for obj_summary in source_bucket.objects.filter(Prefix=prefix):
            relative_path = obj_summary.key[len(prefix):]
            new_prefix = target_prefix if target_prefix else prefix
            new_key = f"{new_prefix}{relative_path}"

            copy_source = {"Bucket": source_bucket.name, "Key": obj_summary.key}
            target_bucket.copy(copy_source, new_key)
            logger.info(f"Copied {obj_summary.key} -> {new_key}")
    except Exception as e:
        logger.error(f"Error copying directory from {source_bucket.name} to {target_bucket.name}: {e}")
        raise


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
    key = f"{user_name}/{session_id}/{image_name}"

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
    key = f"{user_name}/{session_id}/{file_name}"

    file_size = Path(file_path).stat().st_size
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds limit of {MAX_FILE_SIZE / 1024 / 1024} MB")
    try:
        s3_client.upload_file(
            Filename=file_path,
            Bucket=USERS_BUCKET_NAME,
            Key=key,
            ExtraArgs={
                "Metadata": {"description": description} if description else {}
            }
        )
        logger.info(f"Uploaded file to {USERS_BUCKET_NAME}/{key}")
        return public_file_url(user_name, session_id, file_name)
    except (BotoCoreError, ClientError) as e:
        logger.info(f"Error uploading file: {e}")
        raise


def save_spec(user_name: str, session_id: str, spec: str):
    save_file_to_private(user_name, session_id, "spec.txt", spec.encode("utf8"), "text/plain")


def read_spec_text(user_name: str, session_id: str) -> str | None:
    key = f"{user_name}/{session_id}/spec.txt"
    try:
        obj = s3.Object(USERS_BUCKET_NAME, key)
        return obj.get()["Body"].read().decode("utf-8")
    except s3_client.exceptions.NoSuchKey:
        return None


def read_index_html(user_name: str, session_id: str) -> str:
    key = f"{user_name}/{session_id}/index.html"
    obj = s3.Object(USERS_BUCKET_NAME, key)
    return obj.get()["Body"].read().decode("utf-8")


def read_image_from_private(user_name: str, session_id: str, image_name: str) -> Tuple[bytes, dict[str, str]] | None:
    key = f"{user_name}/{session_id}/images/{image_name}"
    obj = s3.Object(USERS_BUCKET_NAME, key)

    try:
        response = obj.get()
    except s3_client.exceptions.NoSuchKey:
        return None

    metadata = obj.metadata or {}
    return response["Body"].read(), metadata


def save_file_to_private(user_name: str, session_id: str, file_name: str, content: bytes, content_type: str):
    key = f"{user_name}/{session_id}/{file_name}"
    s3_client.put_object(
        Bucket=USERS_BUCKET_NAME,
        Key=key,
        Body=content,
        ContentType=content_type
    )


def load_template(user_name: str, session_id: str, template_name: str):
    _copy_directory_s3(
        source_bucket=s3_bucket,
        target_bucket=s3_bucket,
        prefix=f"templates/{template_name}/",
        target_prefix=f"{user_name}/{session_id}/"
    )


def make_dir_tree() -> DirTree:
    return defaultdict(make_dir_tree)


def register_file(parts: list[str], tree: DirTree):
    current = tree
    for part in parts[:-1]:
        current = current[part]
    return current


def list_s3_structured(user_name: str, session_id: str) -> DirTree:
    prefix = f"{user_name}/{session_id}/"
    files = make_dir_tree()

    for obj_summary in s3_bucket.objects.filter(Prefix=prefix):
        full_key = obj_summary.key
        relative_path = full_key[len(prefix):]
        parts = relative_path.split("/")
        file_name = parts[-1]

        # You need to explicitly fetch the object to get metadata
        obj = s3_bucket.Object(full_key)
        obj_metadata = obj.metadata
        description = obj_metadata.get("description", "No description")

        file = register_file(parts, files)
        file[file_name] = {"__description__": description}

    return files


def format_tree(tree: DirTree, indent=0):
    lines = []
    for key, value in sorted(tree.items()):
        if isinstance(value, dict) and "__description__" in value:
            desc = value["__description__"]
            lines.append("  " * indent + f"- {key} ({desc})")
        else:
            lines.append("  " * indent + f"{key}/")
            lines.extend(format_tree(value, indent + 1))
    return lines


def list_files_in_private(user_name: str, session_id: str):
    structured = list_s3_structured(user_name, session_id)
    files_prefix = public_file_url(user_name, session_id, "")
    file_list = "\n".join(format_tree(structured))
    return f"{files_prefix} contains the following files:\n{file_list}"


def get_public_url(site_name: str) -> str:
    return f"https://{site_name}.breba.site"


# TODO: user_name/session_id are state for the entire request, should probably create a user_cloud_storage class
def upload_site(user_name: str, session_id: str, site_name: str):
    """
    Uploads site to google cloud
    Example: upload_site("/Users/yason/breba/disc-site/sites/test-site", "test-site")
    :param user_name: username
    :param session_id: session id used for locating site files
    :param site_name: site name where all the files will be stored
    :return: public url of deployed site
    """
    # Sanitize site name so that it is a valid URL, but also not case-sensitive
    site_name = re.sub("[^0-9a-zA-Z]+", "-", site_name).strip(" -").lower()

    # TODO: convert to async because GCP is a blocking call, we don't want to have to wait
    # TODO: when empty dir is being uploaded, should pass back an error message
    _copy_directory_s3(
        source_bucket=s3_bucket,
        target_bucket=public_s3_bucket,
        prefix=f"{user_name}/{session_id}/",
        target_prefix=site_name + "/"
    )

    return get_public_url(site_name)
