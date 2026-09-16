"""A field definition, and a value read through one.

The distinction this module draws is the whole point of OpenSEGY:

    a FieldDef says *where a value would be and what it would mean*;
    a Reading says *what was actually there*.

A Reading keeps the raw bytes next to the decoded value. That is deliberate and
non-negotiable: when a delivery turns out to carry centimetres where the card
promised metres, or a vendor's own field where the standard puts the crossline,
the only thing that settles the argument is the bytes. Discarding them to save
four bytes per field would trade the one piece of evidence for nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .types import DTYPE_BYTES, Endian, decode_scalar


@dataclass(frozen=True, slots=True)
class FieldDef:
    """Where a header field lives, per some standard or declaration.

    `start` is 1-based and inclusive, relative to the block the field belongs to
    (byte 1 of the binary header is file byte 3201; byte 1 of a trace header is
    the first byte of that trace). `since` is the revision that first defined
    the field, which is how a rev-1 file carrying rev-2 fields gets noticed.
    """

    name: str
    start: int
    dtype: str
    description: str = ""
    since: tuple[int, int] = (0, 0)
    #: "standard" for a field the SEG specification defines, "vendor" for one a
    #: SEG:Layout stanza or an EBCDIC card declares, "unassigned" for space the
    #: standard leaves free.
    origin: str = "standard"

    @property
    def width(self) -> int:
        if self.dtype.startswith("char"):
            return int(self.dtype[4:])
        return DTYPE_BYTES[self.dtype]

    @property
    def end(self) -> int:
        return self.start + self.width - 1

    def read(self, block: bytes, *, endian: Endian = Endian.BIG,
             block_offset: int = 0, source: str = "") -> "Reading":
        """Decode this field out of `block`.

        `block_offset` is the file byte at which `block` starts, 1-based, so the
        Reading can report an absolute position. A field that runs past the end
        of the block yields a Reading with `value=None` and `truncated=True`
        rather than an exception.
        """
        lo = self.start - 1
        raw = block[lo:lo + self.width]
        truncated = len(raw) != self.width
        value = None if truncated else decode_scalar(raw, self.dtype, endian)
        base = block_offset - 1 if block_offset else 0
        return Reading(
            name=self.name,
            start=base + self.start,
            end=base + self.end,
            dtype=self.dtype,
            raw=raw,
            value=value,
            source=source,
            origin=self.origin,
            since=self.since,
            description=self.description,
            truncated=truncated,
        )


@dataclass(frozen=True, slots=True)
class Reading:
    """One value, and everything needed to argue about it later."""

    name: str
    start: int            # 1-based, inclusive, absolute in the file
    end: int
    dtype: str
    raw: bytes
    value: Any
    source: str = ""      # "binary_header", "trace_header", "trace_header_ext_1", ...
    origin: str = "standard"
    since: tuple[int, int] = (0, 0)
    description: str = ""
    truncated: bool = False
    #: Set when a code has a meaning worth spelling out, e.g. format 5 →
    #: "4-byte IEEE float". Never replaces `value`; sits beside it.
    interpretation: str | None = None

    @property
    def byte_range(self) -> tuple[int, int]:
        return (self.start, self.end)

    @property
    def hex(self) -> str:
        return self.raw.hex(" ")

    def with_interpretation(self, text: str | None) -> "Reading":
        if text is None:
            return self
        return Reading(**{**_as_dict(self), "interpretation": text})

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe, for the API and the inspector. Raw bytes go as hex."""
        return {
            "name": self.name,
            "byte_range": [self.start, self.end],
            "dtype": self.dtype,
            "raw_hex": self.hex,
            "value": self.value,
            "interpretation": self.interpretation,
            "source": self.source,
            "origin": self.origin,
            "since_revision": f"{self.since[0]}.{self.since[1]}",
            "description": self.description,
            "truncated": self.truncated,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging convenience
        shown = self.interpretation or self.value
        return f"<{self.name} @{self.start}-{self.end} {self.dtype}={shown!r}>"


def _as_dict(r: Reading) -> dict[str, Any]:
    return {f: getattr(r, f) for f in Reading.__slots__}


class HeaderView:
    """A parsed block of header fields, addressable by name or byte position.

    Dict-like access returns the *value*, because that is what calling code
    almost always wants; `.reading(name)` returns the whole Reading when the
    argument is about provenance. Both views are over the same objects.
    """

    __slots__ = ("_readings", "_by_name", "block", "block_offset", "endian")

    def __init__(self, readings: list[Reading], *, block: bytes,
                 block_offset: int, endian: Endian) -> None:
        self._readings = readings
        self._by_name = {r.name: r for r in readings}
        self.block = block
        self.block_offset = block_offset
        self.endian = endian

    def __getitem__(self, name: str) -> Any:
        return self._by_name[name].value

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __iter__(self):
        return iter(self._readings)

    def __len__(self) -> int:
        return len(self._readings)

    def get(self, name: str, default: Any = None) -> Any:
        r = self._by_name.get(name)
        return default if r is None else r.value

    def reading(self, name: str) -> Reading | None:
        return self._by_name.get(name)

    def at(self, byte: int) -> Reading | None:
        """Which field covers this 1-based absolute byte, if any."""
        for r in self._readings:
            if r.start <= byte <= r.end:
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        return {r.name: r.to_dict() for r in self._readings}

    def values(self) -> dict[str, Any]:
        return {r.name: r.value for r in self._readings}
