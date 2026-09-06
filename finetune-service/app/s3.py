from functools import lru_cache

import boto3
from botocore.client import Config

from app.config import get_settings

settings = get_settings()


@lru_cache
def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def download_object(key: str, dest: str) -> None:
    s3_client().download_file(settings.s3_bucket, key, dest)


def upload_json(key: str, body: bytes) -> None:
    s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
