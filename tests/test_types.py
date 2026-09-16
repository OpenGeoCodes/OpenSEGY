import math

import pytest

from opensegy.types import (
    SAMPLE_BYTES,
    SAMPLE_DTYPE,
    Endian,
    decode_scalar,
    encode_scalar,
    float_to_ibm32,
    ibm32_to_float,
)


def test_ibm_float_decodes_the_textbook_value():
    # 0x4276A000 is the canonical IBM hexadecimal float example.
    assert ibm32_to_float(bytes.fromhex("4276A000")) == 118.625


@pytest.mark.parametrize("value", [0.0, 1.0, -1.0, 118.625, 3.14159, -12345.678, 1e-5, 1e5])
def test_ibm_float_round_trips_within_its_own_precision(value):
    back = ibm32_to_float(float_to_ibm32(value))
    assert back == pytest.approx(value, rel=1e-6, abs=1e-9)


@pytest.mark.parametrize("dtype,value", [
    ("int8", -12), ("uint8", 250),
    ("int16", -32000), ("uint16", 65000),
    ("int24", -8_000_000), ("uint24", 16_000_000),
    ("int32", -2_000_000_000), ("uint32", 4_000_000_000),
    ("int64", -9_000_000_000_000), ("uint64", 18_000_000_000_000),
    ("ieee32", 2.5), ("ieee64", 2.5),
])
@pytest.mark.parametrize("endian", [Endian.BIG, Endian.LITTLE])
def test_every_header_type_round_trips_in_both_byte_orders(dtype, value, endian):
    raw = encode_scalar(value, dtype, endian)
    assert decode_scalar(raw, dtype, endian) == value


def test_byte_order_actually_changes_the_bytes():
    assert encode_scalar(1, "int32", Endian.BIG) != encode_scalar(1, "int32", Endian.LITTLE)


def test_a_short_buffer_decodes_to_none_rather_than_raising():
    # A truncated file must still be describable; one unreadable field is not a
    # reason to refuse to describe the other three hundred.
    assert decode_scalar(b"\x00", "int32") is None


def test_every_sample_format_has_a_width_and_a_decoder():
    assert set(SAMPLE_BYTES) == set(SAMPLE_DTYPE) | {4}
    for code, dtype in SAMPLE_DTYPE.items():
        assert SAMPLE_BYTES[code] == len(encode_scalar(1, dtype))


def test_text_fields_pad_and_strip():
    assert encode_scalar("EXT1", "char8") == b"EXT1\x00\x00\x00\x00"
    assert decode_scalar(b"EXT1\x00\x00\x00\x00", "char8") == "EXT1"
