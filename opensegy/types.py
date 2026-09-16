"""Data types, sample-format codes and byte order.

Everything here is a *fact from the standard*, kept in one place so the header
tables and the trace reader cannot drift apart. Byte positions throughout
OpenSEGY are **1-based and inclusive**, because that is how the SEG-Y
specification writes them ("bytes 189-192") and how every processor's textual
header states its layout. Converting to 0-based at the last moment, once, is far
less error-prone than carrying two conventions.
"""
from __future__ import annotations

import struct
from enum import IntEnum


class Endian(IntEnum):
    """How to read multi-byte integers.

    Rev 2 put a known 32-bit constant at bytes 3297-3300 so that byte order can
    be *read* rather than guessed. A file written before Rev 2 leaves it zero,
    and then the only honest answer is "assume big-endian and check whether the
    numbers come out plausible" — which is what `structure.detect_endian` does.
    """

    BIG = 0
    LITTLE = 1

    @property
    def prefix(self) -> str:
        return ">" if self is Endian.BIG else "<"


#: The constant Rev 2 writes at bytes 3297-3300, read big-endian.
BYTE_ORDER_CONSTANT = 0x01020304
#: The same constant seen by a reader using the opposite byte order.
BYTE_ORDER_REVERSED = 0x04030201
#: Pairwise-swapped, which is what a PDP-endian tape produces.
BYTE_ORDER_PAIRWISE = 0x02010403


class SampleFormat(IntEnum):
    """Data sample format codes (binary header bytes 3225-3226).

    Codes 6, 7, 9-12, 15 and 16 arrived with Rev 2. Code 4 is fixed-point with
    gain, withdrawn after Rev 1 and listed here only so a file that still
    declares it can be *named* rather than rejected as unknown.
    """

    IBM_FLOAT32 = 1
    INT32 = 2
    INT16 = 3
    FIXED_POINT_GAIN32 = 4
    IEEE_FLOAT32 = 5
    IEEE_FLOAT64 = 6
    INT24 = 7
    INT8 = 8
    INT64 = 9
    UINT32 = 10
    UINT16 = 11
    UINT64 = 12
    UINT24 = 15
    UINT8 = 16


#: Bytes per sample for each format code.
SAMPLE_BYTES: dict[int, int] = {
    1: 4, 2: 4, 3: 2, 4: 4, 5: 4, 6: 8, 7: 3, 8: 1,
    9: 8, 10: 4, 11: 2, 12: 8, 15: 3, 16: 1,
}

#: Human labels, used in findings and in the inspector.
SAMPLE_FORMAT_NAMES: dict[int, str] = {
    1: "4-byte IBM float", 2: "4-byte int", 3: "2-byte int",
    4: "4-byte fixed-point with gain (withdrawn after rev 1)",
    5: "4-byte IEEE float", 6: "8-byte IEEE float", 7: "3-byte int",
    8: "1-byte int", 9: "8-byte int", 10: "4-byte unsigned int",
    11: "2-byte unsigned int", 12: "8-byte unsigned int",
    15: "3-byte unsigned int", 16: "1-byte unsigned int",
}

#: Which revision first defined each sample format code. Used to notice that a
#: file declaring rev 1 is carrying rev 2 data — one of the structural signals
#: that separates *declared* from *detected* revision.
SAMPLE_FORMAT_SINCE: dict[int, tuple[int, int]] = {
    1: (0, 0), 2: (0, 0), 3: (0, 0), 4: (0, 0), 5: (1, 0), 8: (1, 0),
    6: (2, 0), 7: (2, 0), 9: (2, 0), 10: (2, 0), 11: (2, 0), 12: (2, 0),
    15: (2, 0), 16: (2, 0),
}


#: Width in bytes of each header field type.
DTYPE_BYTES: dict[str, int] = {
    "int8": 1, "uint8": 1,
    "int16": 2, "uint16": 2,
    "int24": 3, "uint24": 3,
    "int32": 4, "uint32": 4,
    "int64": 8, "uint64": 8,
    "ieee32": 4, "ieee64": 8,
    "ibm32": 4,
}

_STRUCT_CODE: dict[str, str] = {
    "int8": "b", "uint8": "B",
    "int16": "h", "uint16": "H",
    "int32": "i", "uint32": "I",
    "int64": "q", "uint64": "Q",
    "ieee32": "f", "ieee64": "d",
}


def decode_scalar(raw: bytes, dtype: str, endian: Endian = Endian.BIG):
    """Decode one header value. `raw` must already be exactly the right width.

    Text fields are named `charN` and come back as a `str`; everything else is
    numeric. A short or malformed buffer returns None rather than raising,
    because a truncated file must still be describable — refusing to decode one
    field is not a reason to refuse to describe the other three hundred.
    """
    if dtype.startswith("char"):
        return raw.decode("ascii", errors="replace").rstrip("\x00 ")

    width = DTYPE_BYTES.get(dtype)
    if width is None or len(raw) != width:
        return None

    if dtype == "ibm32":
        return ibm32_to_float(raw, endian)

    if dtype in ("int24", "uint24"):
        # Rev 2 added 3-byte samples, which `struct` cannot express. Sign is
        # carried by the most significant byte in the file's own byte order.
        ordered = raw if endian is Endian.BIG else raw[::-1]
        value = int.from_bytes(ordered, "big", signed=dtype == "int24")
        return value

    return struct.unpack(endian.prefix + _STRUCT_CODE[dtype], raw)[0]


def ibm32_to_float(raw: bytes, endian: Endian = Endian.BIG) -> float:
    """IBM System/360 hexadecimal float to IEEE double.

    Base-16 exponent biased by 64, 24-bit fraction, sign-magnitude. Kept as
    scalar arithmetic here because header fields are read one at a time; bulk
    trace conversion gets a vectorised path when trace data lands.
    """
    word = struct.unpack(endian.prefix + "I", raw)[0]
    if word == 0:
        return 0.0
    sign = -1.0 if word & 0x80000000 else 1.0
    exponent = ((word >> 24) & 0x7F) - 64
    fraction = (word & 0x00FFFFFF) / float(1 << 24)
    return sign * fraction * (16.0 ** exponent)


def encode_scalar(value, dtype: str, endian: Endian = Endian.BIG) -> bytes:
    """The inverse of `decode_scalar`.

    It lives here, beside the decoder, so that the synthetic builder and the
    future writer cannot drift from the reader: one table of widths, one pair of
    functions. A value that does not fit its field raises, because writing is
    where strictness belongs — the tolerance this library shows is for files it
    is handed, never for files it produces.
    """
    if dtype.startswith("char"):
        width = int(dtype[4:])
        raw = str(value).encode("ascii", errors="replace")[:width]
        return raw.ljust(width, b"\x00")

    width = DTYPE_BYTES[dtype]
    if dtype == "ibm32":
        return float_to_ibm32(float(value), endian)

    if dtype in ("int24", "uint24"):
        signed = dtype == "int24"
        try:
            raw = int(value).to_bytes(3, "big", signed=signed)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{value!r} does not fit a {dtype} field") from exc
        return raw if endian is Endian.BIG else raw[::-1]

    code = _STRUCT_CODE[dtype]
    if dtype.startswith(("int", "uint")):
        value = int(value)
    else:
        value = float(value)
    try:
        return struct.pack(endian.prefix + code, value)
    except struct.error as exc:
        # Writing is where strictness belongs, but the message should say what
        # went wrong rather than leak `struct`'s idea of a format character.
        raise ValueError(
            f"{value!r} does not fit a {dtype} field ({exc})") from exc


def float_to_ibm32(value: float, endian: Endian = Endian.BIG) -> bytes:
    """IEEE double to IBM System/360 hexadecimal float."""
    if value == 0 or value != value:
        return struct.pack(endian.prefix + "I", 0)
    sign = 0x80000000 if value < 0 else 0
    value = abs(value)
    exponent = 0
    while value >= 1.0:
        value /= 16.0
        exponent += 1
    while value < 1.0 / 16.0:
        value *= 16.0
        exponent -= 1
    fraction = int(round(value * (1 << 24)))
    if fraction >= (1 << 24):          # rounding pushed it over; renormalise
        fraction >>= 4
        exponent += 1
    word = sign | (((exponent + 64) & 0x7F) << 24) | (fraction & 0x00FFFFFF)
    return struct.pack(endian.prefix + "I", word)


#: Sample format code → the header dtype that decodes one sample of it. Shared
#: by the trace reader and the synthetic builder so a fixture cannot be written
#: in a format the reader would decode differently.
SAMPLE_DTYPE: dict[int, str] = {
    1: "ibm32", 2: "int32", 3: "int16", 5: "ieee32", 6: "ieee64",
    7: "int24", 8: "int8", 9: "int64", 10: "uint32", 11: "uint16",
    12: "uint64", 15: "uint24", 16: "uint8",
}
