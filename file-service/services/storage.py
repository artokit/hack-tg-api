import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

import config


def ensure_bucket() -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=config.S3_STORAGE_URL,
        region_name="ru-1",
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        config=Config(s3={"addressing_style": "path"}),
    )
    try:
        s3.head_bucket(Bucket=config.S3_BUCKET_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        try:
            s3.create_bucket(
                Bucket=config.S3_BUCKET_NAME,
                CreateBucketConfiguration={"LocationConstraint": "ru-1"},
            )
        except ClientError as create_error:
            if create_error.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                raise
    finally:
        s3.close()


if __name__ == "__main__":
    ensure_bucket()
