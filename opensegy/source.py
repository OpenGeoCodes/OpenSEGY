"""Where the bytes come from.

OpenSEGY never opens a URL and never imports a storage client. It reads through
whatever object the caller hands it, which needs exactly one method:

    read(offset, length) -> bytes          offset is 0-based

That is enough for a local file, for an fsspec range read against object
storage, for an HTTP server that honours Range, and for a bytes literal in a
test. Keeping the surface this small is what lets the same parser run inside a
backend, inside a converter and inside someone else's notebook.

Header parsing is seek-heavy and the blocks are small, so `ByteSource` also
offers `read_many`, which a remote implementation can override to coalesce a
batch of ranges into one request. The default just loops.
"""
from __future__ import annotations

import os
from typing import Iterable, Protocol, runtime_checkable


@runtime_checkable
class ByteSource(Protocol):
    """The whole contract."""

    def read(self, offset: int, length: int) -> bytes: ...

    @property
    def size(self) -> int | None: ...


class _BaseSource:
    def read_many(self, ranges: Iterable[tuple[int, int]]) -> list[bytes]:
        return [self.read(off, length) for off, length in ranges]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        pass


class MemorySource(_BaseSource):
    """Bytes already in hand. The fixture workhorse."""

    __slots__ = ("_buf",)

    def __init__(self, data: bytes) -> None:
        self._buf = data

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        return self._buf[offset:offset + length]

    @property
    def size(self) -> int:
        return len(self._buf)


class FileSource(_BaseSource):
    """A local file, kept open.

    The handle is held rather than reopened per read because a full header scan
    is one seek and one short read per trace; reopening would dominate the cost.
    """

    __slots__ = ("_fh", "_size", "path")

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = os.fspath(path)
        self._fh = open(self.path, "rb")
        self._size = os.fstat(self._fh.fileno()).st_size

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        self._fh.seek(offset)
        return self._fh.read(length)

    @property
    def size(self) -> int:
        return self._size

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


def as_source(obj) -> ByteSource:
    """Accept a path, raw bytes, or something that already reads ranges."""
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return MemorySource(bytes(obj))
    if isinstance(obj, (str, os.PathLike)):
        return FileSource(obj)
    if hasattr(obj, "read") and hasattr(obj, "size"):
        return obj
    raise TypeError(
        f"cannot read SEG-Y from {type(obj).__name__}; pass a path, bytes, "
        "or an object with read(offset, length) and .size"
    )
