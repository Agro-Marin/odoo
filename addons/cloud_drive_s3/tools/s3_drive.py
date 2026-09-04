import logging

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_BUCKET = "cloud_drive_s3.bucket_name"
PARAM_REGION = "cloud_drive_s3.region"
CREDENTIAL_CATEGORY_XMLID = "cloud_drive_s3.credential_category_drive_s3"

DRIVE_PREFIX = ""

DOWNLOAD_URL_EXPIRY = 300
UPLOAD_URL_EXPIRY = 300
MAX_UPLOAD_BYTES = 5 * 1024**3

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}


def _is_image(name):
    return "." in name and name.rsplit(".", 1)[-1].lower() in _IMAGE_EXTS


_DriveClientCache = {}


def _get_credential(env):
    category = env.ref(CREDENTIAL_CATEGORY_XMLID, raise_if_not_found=False)
    if not category:
        return env["credential.credential"]
    return (
        env["credential.credential"]
        .sudo()
        .search(
            [("category_id", "=", category.id), ("active", "=", True)],
            order="write_date desc, id desc",
            limit=1,
        )
    )


def get_drive_client(env):
    icp = env["ir.config_parameter"].sudo()
    bucket = icp.get_param(PARAM_BUCKET)
    region = icp.get_param(PARAM_REGION)
    credential = _get_credential(env)
    if not (bucket and region and credential):
        raise UserError(
            env._(
                "The Cloud drive is not fully configured. Set the bucket, region "
                "and IAM keys in Cloud → Configuration."
            )
        )

    signature = (bucket, region, credential.id, str(credential.write_date))
    db_name = env.registry.db_name
    cached_sig, cached_client, cached_bucket = _DriveClientCache.get(
        db_name, (None, None, None)
    )
    if cached_sig == signature and cached_client:
        return cached_client, cached_bucket

    keys = credential.get_credential_dict()
    access_key_id = keys.get("access_key_id")
    secret_access_key = keys.get("secret_access_key")
    if not (access_key_id and secret_access_key):
        raise UserError(env._("The Cloud drive IAM keys are missing or unreadable."))

    client = boto3.client(
        "s3",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
    )
    _DriveClientCache[db_name] = (signature, client, bucket)
    return client, bucket


def clear_cache(env):
    _DriveClientCache.pop(env.registry.db_name, None)


def _clean_rel(env, path):
    path = (path or "").strip().lstrip("/")
    if "\\" in path or "\x00" in path:
        raise UserError(env._("Invalid path: %s", path))
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UserError(env._("Invalid path: %s", path))
    return "/".join(parts)


def _full_prefix(env, path):
    rel = _clean_rel(env, path)
    return DRIVE_PREFIX + (rel + "/" if rel else "")


def _full_key(env, path):
    rel = _clean_rel(env, path)
    if not rel:
        raise UserError(env._("A file path is required."))
    return DRIVE_PREFIX + rel


def list_path(env, path="", folder_visible=None, file_visible=None):
    client, bucket = get_drive_client(env)
    prefix = _full_prefix(env, path)
    folders, files = [], []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for common in page.get("CommonPrefixes", []):
            full = common["Prefix"]
            entry = {
                "name": full[len(prefix) : -1],
                "path": full[len(DRIVE_PREFIX) : -1],
            }
            if folder_visible is None or folder_visible(entry["path"]):
                folders.append(entry)
        for obj in page.get("Contents", []):
            key = obj["Key"]
            name = key[len(prefix) :]
            if not name or name.endswith("/"):
                continue
            drive_key = key[len(DRIVE_PREFIX) :]
            if file_visible is not None and not file_visible(drive_key):
                continue
            entry = {
                "name": name,
                "key": drive_key,
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "is_image": _is_image(name),
            }
            if entry["is_image"]:
                entry["preview_url"] = _presign_get(client, bucket, key)
            files.append(entry)
    return {"folders": folders, "files": files}


def _presign_get(client, bucket, key, disposition=None):
    params = {"Bucket": bucket, "Key": key}
    if disposition:
        params["ResponseContentDisposition"] = disposition
    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=DOWNLOAD_URL_EXPIRY,
    )


def presign_download(env, key):
    client, bucket = get_drive_client(env)
    return _presign_get(client, bucket, _full_key(env, key), disposition="attachment")


def presign_upload(env, key, content_type=None):
    client, bucket = get_drive_client(env)
    fields = {}
    conditions = [["content-length-range", 0, MAX_UPLOAD_BYTES]]
    if content_type:
        fields["Content-Type"] = content_type
        conditions.append({"Content-Type": content_type})
    return client.generate_presigned_post(
        Bucket=bucket,
        Key=_full_key(env, key),
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=UPLOAD_URL_EXPIRY,
    )


def delete_file(env, key):
    client, bucket = get_drive_client(env)
    client.delete_object(Bucket=bucket, Key=_full_key(env, key))


def delete_folder(env, path):
    client, bucket = get_drive_client(env)
    prefix = _full_prefix(env, path)
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=2)
    remaining = [o["Key"] for o in resp.get("Contents", []) if o["Key"] != prefix]
    if remaining:
        raise UserError(env._("The folder is not empty."))
    client.delete_object(Bucket=bucket, Key=prefix)


def make_folder(env, parent, name):
    name = (name or "").strip()
    if not name or "/" in name or name in (".", ".."):
        raise UserError(env._("Invalid folder name."))
    client, bucket = get_drive_client(env)
    marker = _full_prefix(env, parent) + name + "/"
    client.put_object(Bucket=bucket, Key=marker, Body=b"")


def _key_exists(client, bucket, key):
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def copy_file(env, src_key, dst_key):
    client, bucket = get_drive_client(env)
    src = _full_key(env, src_key)
    dst = _full_key(env, dst_key)
    if src == dst:
        raise UserError(env._("Source and destination are the same."))
    if _key_exists(client, bucket, dst):
        raise UserError(env._("A file already exists at the destination."))
    client.copy_object(
        Bucket=bucket, CopySource={"Bucket": bucket, "Key": src}, Key=dst
    )


def move_file(env, src_key, dst_key):
    client, bucket = get_drive_client(env)
    src = _full_key(env, src_key)
    dst = _full_key(env, dst_key)
    if src == dst:
        return
    if _key_exists(client, bucket, dst):
        raise UserError(env._("A file already exists at the destination."))
    client.copy_object(
        Bucket=bucket, CopySource={"Bucket": bucket, "Key": src}, Key=dst
    )
    client.delete_object(Bucket=bucket, Key=src)


def _iter_folder_keys(client, bucket, prefix):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            yield obj["Key"]


def _delete_keys(client, bucket, keys):
    for start in range(0, len(keys), 1000):
        chunk = keys[start : start + 1000]
        client.delete_objects(
            Bucket=bucket, Delete={"Objects": [{"Key": k} for k in chunk]}
        )


def _check_folder_move(env, client, bucket, src, dst):
    if not src:
        raise UserError(env._("A folder path is required."))
    if src == dst:
        raise UserError(env._("Source and destination are the same."))
    if dst.startswith(src):
        raise UserError(env._("Cannot move or copy a folder into itself."))
    resp = client.list_objects_v2(Bucket=bucket, Prefix=dst, MaxKeys=1)
    if resp.get("Contents"):
        raise UserError(env._("A folder already exists at the destination."))


def copy_folder(env, src_path, dst_path):
    client, bucket = get_drive_client(env)
    src = _full_prefix(env, src_path)
    dst = _full_prefix(env, dst_path)
    _check_folder_move(env, client, bucket, src, dst)
    keys = list(_iter_folder_keys(client, bucket, src))
    if not keys:
        raise UserError(env._("The folder does not exist or is empty."))
    for key in keys:
        client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=dst + key[len(src) :],
        )


def move_folder(env, src_path, dst_path):
    client, bucket = get_drive_client(env)
    src = _full_prefix(env, src_path)
    dst = _full_prefix(env, dst_path)
    _check_folder_move(env, client, bucket, src, dst)
    keys = list(_iter_folder_keys(client, bucket, src))
    if not keys:
        raise UserError(env._("The folder does not exist or is empty."))
    for key in keys:
        client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=dst + key[len(src) :],
        )
    _delete_keys(client, bucket, keys)


def object_info(env, key):
    client, bucket = get_drive_client(env)
    head = client.head_object(Bucket=bucket, Key=_full_key(env, key))
    return {
        "key": key,
        "size": head["ContentLength"],
        "last_modified": head["LastModified"].isoformat(),
        "content_type": head.get("ContentType", ""),
        "etag": (head.get("ETag") or "").strip('"'),
    }


def _require_versioning(env, client, bucket):
    try:
        resp = client.get_bucket_versioning(Bucket=bucket)
    except (ClientError, BotoCoreError) as exc:
        raise UserError(
            env._(
                "Could not read the versioning status of bucket '%(bucket)s': %(err)s"
            )
            % {"bucket": bucket, "err": exc}
        ) from exc
    if resp.get("Status") != "Enabled":
        raise UserError(
            env._(
                "The Drive bucket '%s' must have versioning enabled so that "
                "overwrites keep the previous version. Enable it in S3 "
                "(Bucket → Properties → Bucket Versioning) and test again.",
                bucket,
            )
        )


def test_connection(env):
    client, bucket = get_drive_client(env)
    try:
        client.head_bucket(Bucket=bucket)
    except (ClientError, BotoCoreError) as exc:
        raise UserError(
            env._("Could not reach bucket '%(bucket)s': %(err)s")
            % {"bucket": bucket, "err": exc}
        ) from exc
    _require_versioning(env, client, bucket)
    return bucket
