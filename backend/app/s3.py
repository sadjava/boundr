from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import get_settings

settings = get_settings()


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


@lru_cache
def internal_s3():
    return _client(settings.s3_endpoint)


@lru_cache
def public_s3():
    return _client(settings.s3_public_endpoint)


def video_s3_key(project_id: str, video_id: str) -> str:
    return f"projects/{project_id}/videos/{video_id}/original.mp4"


def annotation_s3_key(project_id: str, video_id: str) -> str:
    return f"projects/{project_id}/videos/{video_id}/annotation.json"


def fine_tune_s3_prefix(user_id: str, fine_tune_id: str) -> str:
    """Checkpoint prefix outside projects/ so project delete does not wipe weights."""
    return f"users/{user_id}/models/{fine_tune_id}/"


def presigned_put_url(key: str, content_type: str) -> str:
    return public_s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=settings.s3_presign_expires,
    )


def presigned_get_url(key: str) -> str:
    return public_s3().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.s3_presign_expires,
    )


def put_bytes(key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    internal_s3().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def get_bytes(key: str) -> bytes:
    resp = internal_s3().get_object(Bucket=settings.s3_bucket, Key=key)
    return resp["Body"].read()


def delete_object(key: str) -> None:
    try:
        internal_s3().delete_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError:
        pass


def delete_prefix(prefix: str) -> None:
    client = internal_s3()
    token = None
    while True:
        kwargs = {"Bucket": settings.s3_bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        keys = [{"Key": obj["Key"]} for obj in resp.get("Contents") or []]
        if keys:
            client.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": keys})
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")


def object_exists(key: str) -> bool:
    try:
        internal_s3().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def ensure_bucket() -> None:
    client = internal_s3()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)
    try:
        client.put_bucket_cors(
            Bucket=settings.s3_bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": settings.cors_origin_list,
                        "AllowedMethods": ["GET", "PUT", "POST", "HEAD", "DELETE"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag", "Content-Length", "Content-Type"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )
    except ClientError:
        # Newer MinIO builds omit PutBucketCors; compose sets MINIO_API_CORS_ALLOW_ORIGIN.
        pass
