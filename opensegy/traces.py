"""Trace data: the samples, and the headers of every trace at once.

Two operations matter here and they have different shapes.

**One trace, or a slice of them.** A seek and a read, decoded into an array.
The cost is dominated by the read, not the decode.

**Every trace header, and no samples.** This is how a survey's geometry gets
built, and it is the single most common real task. Reading 240 bytes and
skipping the samples costs a few megabytes on a file of many gigabytes, so it
is worth having as its own path rather than as a loop over `header(i)`.

On decoding speed: the only format that needs real work is IBM hexadecimal
float, and vectorised it runs at about 190 MB/s on this hardware, exact against
the scalar decoder. Object storage delivers around 50 MB/s and a WireGuard link
around 100, so the conversion is not the bottleneck and native code would buy a
constant factor on a step nobody is waiting for. IEEE float, which modern files
use, is a byteswap at several GB/s.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence

import numpy as np

from . import trace_header as th
from .fields import FieldDef, HeaderView
from .source import as_source
from .structure import SegyStructure, scan
from .types import SAMPLE_BYTES, Endian

#: Sample format code → the numpy dtype that reads it directly, where one
#: exists. Formats 1 (IBM float), 7 and 15 (three-byte integers) have no native
#: dtype and are handled separately.
_NATIVE_DTYPE: dict[int, str] = {
    2: "i4", 3: "i2", 5: "f4", 6: "f8", 8: "i1",
    9: "i8", 10: "u4", 11: "u2", 12: "u8", 16: "u1",
}


def decode_samples(raw: bytes | np.ndarray, sample_format: int,
                   endian: Endian = Endian.BIG) -> np.ndarray:
    """Decode packed sample bytes into a float32 array.

    Always returns float32. Integer formats are widened rather than kept as
    integers, because a caller who asked for samples wants amplitudes, and the
    formats that are integers on disk are scaled amplitudes in intent.
    """
    buf = raw if isinstance(raw, (bytes, bytearray, memoryview)) else raw.tobytes()
    prefix = ">" if endian is Endian.BIG else "<"

    if sample_format == 1:
        return _ibm_to_float32(buf, endian)
    if sample_format in (7, 15):
        return _int24_to_float32(buf, endian, signed=sample_format == 7)
    if sample_format == 4:
        raise NotImplementedError(
            "sample format 4, fixed-point with gain, was withdrawn after rev 1 "
            "and is not decoded")
    dtype = _NATIVE_DTYPE.get(sample_format)
    if dtype is None:
        raise ValueError(f"unknown sample format code {sample_format}")
    return np.frombuffer(buf, dtype=prefix + dtype).astype(np.float32)


def _ibm_scale_table() -> np.ndarray:
    """One scale factor per possible top byte of an IBM float word.

    The top byte is the sign bit plus the seven exponent bits, so there are only
    256 of them, and the whole conversion collapses to a table lookup and a
    multiply:

        value = mantissa * table[top_byte]

    where ``table[t] = ±2**(4*(e-64) - 24)``. That is one gather and one
    multiply over the data instead of the five passes the arithmetic form needs,
    and it measured 4.3x faster on a 64 MB buffer, exact.

    **The table is clipped to the largest finite float32, and that is not
    cosmetic.** Fifty-two of the 256 exponents scale beyond what float32 holds,
    so an unclipped table stores infinity for them. IBM floats are not
    normalised, which means a word with a large exponent and a zero mantissa is
    a perfectly ordinary way of writing zero, and real files contain them. With
    infinity in the table that zero becomes ``0 * inf``, which is NaN. Clipping
    makes it ``0 * 3.4e38``, which is zero, while a genuinely out-of-range value
    still overflows to infinity on the multiply — the correct float32 answer.
    """
    table = np.zeros(256, dtype=np.float64)
    for top in range(256):
        sign = -1.0 if top & 0x80 else 1.0
        exponent = (top & 0x7F) - 64
        table[top] = sign * 2.0 ** (4 * exponent - 24)
    limit = float(np.finfo(np.float32).max)
    return np.clip(table, -limit, limit).astype(np.float32)


_IBM_SCALE = _ibm_scale_table()


def _ibm_to_float32(buf: bytes, endian: Endian) -> np.ndarray:
    """IBM System/360 hexadecimal float, vectorised.

    Sign-magnitude, base-16 exponent biased by 64, 24-bit fraction, so the value
    is ``fraction / 2**24 * 16**(exponent-64)``. See `_ibm_scale_table` for why
    that becomes a lookup.
    """
    prefix = ">" if endian is Endian.BIG else "<"
    words = np.frombuffer(buf, dtype=prefix + "u4")
    top = np.frombuffer(buf, dtype=np.uint8).reshape(-1, 4)[:, 0 if endian is Endian.BIG else 3]
    out = (words & 0x00FFFFFF).astype(np.float32)
    out *= _IBM_SCALE[top]
    return out


def _int24_to_float32(buf: bytes, endian: Endian, *, signed: bool) -> np.ndarray:
    """Three-byte integers, which rev 2 added and numpy has no dtype for.

    Widened to four bytes by hand, with the sign carried from the top byte.
    """
    raw = np.frombuffer(buf, dtype=np.uint8).reshape(-1, 3)
    if endian is Endian.LITTLE:
        raw = raw[:, ::-1]
    wide = np.zeros((raw.shape[0], 4), dtype=np.uint8)
    wide[:, 1:] = raw
    value = wide.view(">u4").reshape(-1).astype(np.int64)
    if signed:
        value = np.where(value >= 0x800000, value - 0x1000000, value)
    return value.astype(np.float32)


@dataclass
class SegyFile:
    """A SEG-Y open for reading, structure already resolved.

    Held open: `scan` costs one short read, and everything after it is seeks
    against the same handle.
    """

    structure: SegyStructure
    source: Any
    _revision: tuple[int, int] = (1, 0)

    def __post_init__(self) -> None:
        self._revision = self.structure.revision

    # ── lifecycle ────────────────────────────────────────────────────────────

    def __enter__(self) -> "SegyFile":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        close = getattr(self.source, "close", None)
        if close:
            close()

    # ── shape ────────────────────────────────────────────────────────────────

    @property
    def n_traces(self) -> int:
        count = self.structure.trace_count
        if count is None:
            raise ValueError(
                "this file's trace count is unknown; it has variable-length "
                "traces and needs an index")
        return int(count)

    @property
    def n_samples(self) -> int:
        n = self.structure.sample_count
        if not n:
            raise ValueError("this file declares no sample count")
        return int(n)

    @property
    def findings(self):
        return self.structure.findings

    def __len__(self) -> int:
        return self.n_traces

    # ── reading ──────────────────────────────────────────────────────────────

    def _offset(self, index: int) -> int:
        if index < 0:
            index += self.n_traces
        if not 0 <= index < self.n_traces:
            raise IndexError(f"trace {index} is outside 0..{self.n_traces - 1}")
        return self.structure.trace_offset(index)

    def header(self, index: int) -> HeaderView:
        """The standard 240-byte trace header of one trace."""
        offset = self._offset(index)
        block = self.source.read(offset, th.TRACE_HEADER_SIZE)
        return th.parse(block, major=self._revision[0], minor=self._revision[1],
                        endian=self.structure.endian, offset=offset)

    def header_extensions(self, index: int) -> list[HeaderView]:
        """The additional trace headers rev 2 allows, if the file declares any."""
        n = self.structure.extra_trace_headers
        if not n:
            return []
        offset = self._offset(index)
        blocks = [self.source.read(offset + (i + 1) * th.TRACE_HEADER_SIZE,
                                   th.TRACE_HEADER_SIZE) for i in range(n)]
        return th.parse_trace([b""] + blocks, major=self._revision[0],
                              minor=self._revision[1],
                              endian=self.structure.endian, offset=offset)[1:]

    def trace(self, index: int) -> np.ndarray:
        """The samples of one trace, as float32."""
        offset = self._offset(index)
        header_bytes = th.TRACE_HEADER_SIZE * (1 + self.structure.extra_trace_headers)
        n = self.n_samples
        width = SAMPLE_BYTES[self.structure.sample_format]
        raw = self.source.read(offset + header_bytes, n * width)
        if len(raw) < n * width:
            raise EOFError(
                f"trace {index} is truncated: {len(raw)} bytes of {n * width}")
        return decode_samples(raw, self.structure.sample_format,
                              self.structure.endian)

    def traces(self, start: int = 0, stop: int | None = None) -> np.ndarray:
        """A contiguous range of traces as a (n_traces, n_samples) array.

        Read in one go rather than trace by trace, because on object storage the
        difference between one request and a thousand is the whole cost.
        """
        stop = self.n_traces if stop is None else stop
        start = max(0, start)
        stop = min(self.n_traces, stop)
        if stop <= start:
            return np.empty((0, self.n_samples), dtype=np.float32)

        stride = self.structure.trace_bytes
        header_bytes = th.TRACE_HEADER_SIZE * (1 + self.structure.extra_trace_headers)
        n = self.n_samples
        width = SAMPLE_BYTES[self.structure.sample_format]
        block = self.source.read(self.structure.trace_offset(start),
                                 (stop - start) * stride)
        rows = np.frombuffer(block, dtype=np.uint8)[:(stop - start) * stride]
        rows = rows.reshape(-1, stride)[:, header_bytes:header_bytes + n * width]
        return decode_samples(np.ascontiguousarray(rows).tobytes(),
                              self.structure.sample_format,
                              self.structure.endian).reshape(-1, n)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self.traces(index.start or 0, index.stop)
        return self.trace(index)

    def __iter__(self) -> Iterator[np.ndarray]:
        for i in range(self.n_traces):
            yield self.trace(i)

    # ── every header at once ─────────────────────────────────────────────────

    def header_block(self, start: int = 0, stop: int | None = None,
                     *, step: int = 1, chunk: int = 4096) -> np.ndarray:
        """Raw trace headers as an (n, 240) uint8 array.

        Reads 240 bytes per trace and skips the samples, so a 40 GB volume costs
        a few hundred megabytes rather than 40 GB. Traces are read in runs so
        that a remote source sees a manageable number of requests.
        """
        stop = self.n_traces if stop is None else min(stop, self.n_traces)
        indices = range(start, stop, step)
        out = np.empty((len(indices), th.TRACE_HEADER_SIZE), dtype=np.uint8)
        stride = self.structure.trace_bytes

        if step == 1:
            # Contiguous: pull whole traces in runs and keep the first 240 bytes
            # of each. One request per run instead of one per trace.
            written = 0
            for lo in range(start, stop, chunk):
                hi = min(lo + chunk, stop)
                block = self.source.read(self.structure.trace_offset(lo),
                                         (hi - lo) * stride)
                rows = np.frombuffer(block, dtype=np.uint8)[:(hi - lo) * stride]
                rows = rows.reshape(-1, stride)[:, :th.TRACE_HEADER_SIZE]
                out[written:written + rows.shape[0]] = rows
                written += rows.shape[0]
            return out[:written]

        for row, i in enumerate(indices):
            out[row] = np.frombuffer(
                self.source.read(self.structure.trace_offset(i),
                                 th.TRACE_HEADER_SIZE), dtype=np.uint8)
        return out

    def header_table(self, fields: Sequence[str] | None = None, *,
                     start: int = 0, stop: int | None = None,
                     step: int = 1) -> dict[str, np.ndarray]:
        """Named trace-header fields for many traces, as columns.

        This is what building a survey's geometry actually needs: the inline,
        the crossline, the coordinates and the scalar for every trace, without
        touching a single sample.
        """
        block = self.header_block(start, stop, step=step)
        table = {f.name: f for f in th.fields_for(*self._revision)}
        wanted = list(fields) if fields else list(table)
        out: dict[str, np.ndarray] = {}
        for name in wanted:
            fd = table.get(name)
            if fd is None:
                raise KeyError(f"{name!r} is not a standard trace-header field")
            out[name] = _column(block, fd, self.structure.endian)
        return out


def _column(block: np.ndarray, fd: FieldDef, endian: Endian) -> np.ndarray:
    """One field, decoded out of every row of a raw header block."""
    prefix = ">" if endian is Endian.BIG else "<"
    lo = fd.start - 1
    raw = np.ascontiguousarray(block[:, lo:lo + fd.width])
    kind = {"int16": "i2", "uint16": "u2", "int32": "i4", "uint32": "u4",
            "int64": "i8", "uint64": "u8", "int8": "i1", "uint8": "u1",
            "ieee32": "f4", "ieee64": "f8"}.get(fd.dtype)
    if kind is None:
        raise ValueError(f"field {fd.name} has no vectorised decoder ({fd.dtype})")
    return raw.view(prefix + kind).reshape(-1)


def open(obj, **kw) -> SegyFile:      # noqa: A001 - mirrors segyio.open
    """Open a SEG-Y for reading. Accepts a path, bytes, or a byte source."""
    source = as_source(obj)
    return SegyFile(structure=scan(source, **kw), source=source)
