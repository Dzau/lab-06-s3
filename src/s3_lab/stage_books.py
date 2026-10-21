#!/usr/bin/env python3
"""
stage_books.py

Download the Project Gutenberg books listed in a URL file, create an S3 bucket,
make it publicly readable, and upload the books plus an index.html page.

Usage:
    uv run python src/s3_lab/stage_books.py book_urls.txt index.html public-mst3k
"""

import json
import logging
import os
import sys
import time

import boto3
import requests
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError

# Logger setup: timestamped status messages to the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# One S3 client shared by all functions (uses ~/.aws credentials)
s3 = boto3.client("s3", region_name="us-east-1")

# Folder where downloaded books are saved (listed in .gitignore)
DEST_DIR = "books"


def parse_args():
    """
    Read the command line arguments.

    Returns:
        tuple: (list_file, index_path, bucket) as strings.
    """
    if len(sys.argv) < 4:
        log.error(
            "Usage: python stage_books.py BOOK_LIST_FILE INDEX_HTML BUCKET_NAME"
        )
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3]


def download_books(list_file, dest_dir):
    """
    Download every book URL in list_file into dest_dir.

    Books that already exist locally are skipped, so the script can be rerun.

    Args:
        list_file (str): Path to a text file with one URL per line.
        dest_dir (str): Folder to save the books in.

    Returns:
        list: Local paths of all books available after downloading.
    """
    os.makedirs(dest_dir, exist_ok=True)

    # Read the URL list, skipping blank lines
    try:
        with open(list_file, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        log.error(f"Book list not found: {list_file}")
        return []

    log.info(f"Found {len(urls)} book URLs in {list_file}")
    paths = []

    for url in urls:
        # Save under the last part of the URL, e.g. pg1342.txt
        filename = url.rstrip("/").split("/")[-1]
        path = os.path.join(dest_dir, filename)

        if os.path.exists(path):
            log.info(f"Already downloaded, skipping: {path}")
            paths.append(path)
            continue

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()  # raise an error for 404 etc.
            with open(path, "wb") as f:
                f.write(response.content)
            log.info(f"Downloaded {url} -> {path}")
            paths.append(path)
        except requests.RequestException as e:
            log.error(f"Error downloading {url}: {e}")

        # Be polite to Project Gutenberg's servers
        time.sleep(1)

    log.info(f"{len(paths)} of {len(urls)} books available locally")
    return paths


def create_bucket(bucket):
    """
    Create an S3 bucket in us-east-1 unless it already exists.

    Args:
        bucket (str): Bucket name.

    Returns:
        bool: True if the bucket exists afterwards, False otherwise.
    """
    # Check whether the bucket already exists (e.g. from a previous run)
    try:
        s3.head_bucket(Bucket=bucket)
        log.info(f"Bucket already exists: {bucket}")
        return True
    except ClientError:
        log.info(f"Bucket {bucket} not found, creating it")

    # us-east-1 does not take a LocationConstraint
    try:
        s3.create_bucket(Bucket=bucket)
        log.info(f"Created bucket: {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error creating bucket {bucket}: {e}")
        return False


def make_public(bucket):
    """
    Turn off Block Public Access and attach a public-read bucket policy.

    Args:
        bucket (str): Bucket name.

    Returns:
        bool: True on success, False otherwise.
    """
    try:
        # Block Public Access must be off before a public policy is accepted
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info(f"Turned off Block Public Access for {bucket}")

        # Allow anyone to read (GetObject) every object in the bucket
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{bucket}/*",
                }
            ],
        }
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info(f"Attached public-read policy to {bucket}")
        return True
    except ClientError as e:
        log.error(f"Error making {bucket} public: {e}")
        return False


def upload_files(bucket, file_paths):
    """
    Upload each file to the top level of the bucket as plain text.

    Args:
        bucket (str): Bucket name.
        file_paths (list): Local paths of the files to upload.

    Returns:
        int: Number of files uploaded successfully.
    """
    count = 0
    for path in file_paths:
        key = os.path.basename(path)  # pg1342.txt, not books/pg1342.txt
        try:
            s3.upload_file(
                path,
                bucket,
                key,
                ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
            )
            log.info(f"Uploaded {path} -> s3://{bucket}/{key}")
            count += 1
        except (ClientError, S3UploadFailedError, FileNotFoundError) as e:
            log.error(f"Error uploading {path}: {e}")
    log.info(f"Uploaded {count} of {len(file_paths)} books")
    return count


def upload_index(bucket, index_path):
    """
    Upload the index page as index.html so browsers render it.

    Args:
        bucket (str): Bucket name.
        index_path (str): Local path of the index page.

    Returns:
        bool: True on success, False otherwise.
    """
    if not os.path.exists(index_path):
        log.error(f"Index file not found: {index_path}")
        return False
    try:
        s3.upload_file(
            index_path,
            bucket,
            "index.html",
            ExtraArgs={"ContentType": "text/html"},
        )
        log.info(f"Uploaded {index_path} -> s3://{bucket}/index.html")
        return True
    except (ClientError, S3UploadFailedError) as e:
        log.error(f"Error uploading {index_path}: {e}")
        return False


def main():
    """Download the books, set up the public bucket, and upload everything."""
    list_file, index_path, bucket = parse_args()

    book_paths = download_books(list_file, DEST_DIR)
    if not book_paths:
        log.error("No books were downloaded; stopping.")
        sys.exit(1)

    if not create_bucket(bucket):
        log.error("Bucket could not be created; stopping.")
        sys.exit(1)

    if not make_public(bucket):
        log.error("Bucket could not be made public; stopping.")
        sys.exit(1)

    uploaded = upload_files(bucket, book_paths)
    index_ok = upload_index(bucket, index_path)

    url = f"https://{bucket}.s3.amazonaws.com/index.html"
    if uploaded == len(book_paths) and index_ok:
        log.info(f"Success: {uploaded} books and index.html uploaded.")
    else:
        log.warning(
            f"Finished with errors: {uploaded}/{len(book_paths)} books uploaded, "
            f"index.html {'uploaded' if index_ok else 'NOT uploaded'}."
        )
    log.info(f"Public index page: {url}")


if __name__ == "__main__":
    main()
