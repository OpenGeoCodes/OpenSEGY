"""Read a SEG-Y that lives in object storage, without downloading it.

OpenSEGY never opens a URL itself. It reads through whatever object you hand it
that has `read(offset, length)` and `.size`, so an adapter is a few lines and
answering a structural question costs one range request.

    pip install boto3
    python examples/read_from_s3.py my-bucket path/to/survey.sgy
"""
import sys

import boto3

import opensegy


class S3Source:
    """The whole of OpenSEGY's source contract, over HTTP Range.

    Note the inclusive end: S3 ranges are inclusive, OpenSEGY asks for a length.
    Getting that conversion wrong is an off-by-one in every read.
    """

    def __init__(self, bucket: str, key: str, client=None) -> None:
        self.client = client or boto3.client("s3")
        self.bucket, self.key = bucket, key
        self._size = self.client.head_object(Bucket=bucket, Key=key)["ContentLength"]

    def read(self, offset: int, length: int) -> bytes:
        if length <= 0:
            return b""
        end = min(offset + length, self._size) - 1
        if end < offset:
            return b""
        return self.client.get_object(
            Bucket=self.bucket, Key=self.key,
            Range=f"bytes={offset}-{end}")["Body"].read()

    @property
    def size(self) -> int:
        return self._size


def main(bucket: str, key: str) -> int:
    source = S3Source(bucket, key)

    # A few kilobytes read, nothing downloaded.
    segy = opensegy.scan(source)
    print(f"s3://{bucket}/{key}")
    print(f"  revision {segy.revision_label}, {segy.trace_count:,} traces, "
          f"first trace at byte {segy.data_start:,}")

    # Trace access works the same way.
    with opensegy.open(source) as f:
        print(f"  trace 0 peak amplitude {abs(f.trace(0)).max():.4g}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
