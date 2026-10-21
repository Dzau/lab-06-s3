#!/bin/bash
# share_book.sh
# Download one Project Gutenberg book, upload it to a private S3 bucket,
# and print a presigned URL that expires after the given number of seconds.
#
# Usage: ./share_book.sh BOOK_URL BUCKET_NAME EXPIRES_SECONDS
# Example: ./share_book.sh https://www.gutenberg.org/cache/epub/NUMBER/pgNUMBER.txt secret-mst3k 604800

set -euo pipefail

# Validate positional arguments
if [[ $# -ne 3 ]]; then
    echo "Usage: $0 BOOK_URL BUCKET_NAME EXPIRES_SECONDS" >&2
    exit 1
fi

URL="$1"
BUCKET="$2"
EXPIRES="$3"

# Expiration must be a positive whole number of seconds
if ! [[ "$EXPIRES" =~ ^[0-9]+$ ]] || [[ "$EXPIRES" -eq 0 ]]; then
    echo "Error: EXPIRES_SECONDS must be a positive integer, got '$EXPIRES'" >&2
    exit 1
fi

# Keep the file name from the URL, e.g. pg1234.txt
FILENAME="$(basename "$URL")"

# Download the book into books/
mkdir -p books
echo "Downloading $URL -> books/$FILENAME" >&2
curl -fL "$URL" -o "books/$FILENAME"

# Create the bucket unless it already exists (stays private by default)
if aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    echo "Bucket already exists: $BUCKET" >&2
else
    echo "Creating bucket: $BUCKET" >&2
    aws s3 mb "s3://$BUCKET" --region us-east-1 >&2
fi

# Upload the book as plain text so it displays in a browser
echo "Uploading books/$FILENAME -> s3://$BUCKET/$FILENAME" >&2
aws s3 cp "books/$FILENAME" "s3://$BUCKET/$FILENAME" \
    --content-type "text/plain; charset=utf-8" >&2

# Presign a time-limited URL to the private object and print it
echo "Presigned URL (expires in $EXPIRES seconds):" >&2
aws s3 presign "s3://$BUCKET/$FILENAME" --expires-in "$EXPIRES" --region us-east-1
