import pytest

from opensegy import binary_header as bh
from opensegy.types import Endian, encode_scalar


def _table(major, minor=0):
    return {f.name: f for f in bh.fields_for(major, minor)}


def test_rev21_narrows_the_field_rev20_puts_at_byte_3507():
    # The one change between 2.0 and 2.1 that a naive parser gets wrong: the
    # maximum-extra-trace-headers field goes from 32 to 16 bits, and the freed
    # bytes become the survey type.
    assert _table(2, 0)["max_extra_trace_headers"].dtype == "int32"
    assert _table(2, 1)["max_extra_trace_headers"].dtype == "int16"
    assert "survey_type" not in _table(2, 0)
    assert _table(2, 1)["survey_type"].start == 309


def test_field_tables_grow_with_the_revision():
    sizes = [len(bh.fields_for(*r)) for r in [(0, 0), (1, 0), (2, 0), (2, 1)]]
    assert sizes == sorted(sizes)
    assert sizes[0] < sizes[-1]


def test_a_field_reports_its_absolute_position_in_the_file():
    fd = _table(1)["sample_format"]
    assert (fd.start, fd.end) == (25, 26)
    reading = fd.read(b"\x00" * 24 + b"\x00\x05", block_offset=bh.BINARY_HEADER_START)
    assert reading.byte_range == (3225, 3226)
    assert reading.value == 5


def test_coded_fields_carry_a_meaning_beside_the_number():
    block = bytearray(400)
    block[24:26] = encode_scalar(1, "int16")      # IBM float
    block[54:56] = encode_scalar(2, "int16")      # feet
    view = bh.parse(bytes(block), major=1)
    assert view["sample_format"] == 1
    assert view.reading("sample_format").interpretation == "4-byte IBM float"
    assert view.reading("measurement_system").interpretation == "feet"


def test_the_rev2_extended_counts_win_when_they_disagree():
    # Rev 2 added a 32-bit sample count because the 16-bit one overflows past
    # 65535 samples, which a long record at a fine interval reaches easily.
    block = bytearray(400)
    block[20:22] = encode_scalar(1000, "int16")
    block[68:72] = encode_scalar(80000, "int32")
    view = bh.parse(bytes(block), major=2, minor=1)
    assert bh.effective_sample_count(view) == (80000, "ext_samples_per_trace")
    codes = {f.code for f in bh.check(view)}
    assert "binary_header.sample_count_disagrees" in codes


def test_a_16_bit_sample_count_above_32767_is_not_read_as_negative():
    block = bytearray(400)
    block[20:22] = (40000).to_bytes(2, "big")
    view = bh.parse(bytes(block), major=1)
    assert bh.effective_sample_count(view)[0] == 40000


def test_an_unknown_sample_format_is_a_warning_not_an_exception():
    block = bytearray(400)
    block[24:26] = encode_scalar(77, "int16")
    codes = {f.code for f in bh.check(bh.parse(bytes(block), major=1))}
    assert "binary_header.sample_format_unknown" in codes


def test_the_withdrawn_fixed_point_format_is_named_rather_than_rejected():
    block = bytearray(400)
    block[24:26] = encode_scalar(4, "int16")
    codes = {f.code for f in bh.check(bh.parse(bytes(block), major=1))}
    assert "binary_header.sample_format_withdrawn" in codes


def test_unassigned_space_differs_between_revision_families():
    assert (101, 300) in bh.unassigned_ranges(2, 1)
    assert (61, 300) in bh.unassigned_ranges(1, 0)


@pytest.mark.parametrize("endian", [Endian.BIG, Endian.LITTLE])
def test_the_header_parses_in_either_byte_order(endian):
    block = bytearray(400)
    block[20:22] = encode_scalar(1500, "int16", endian)
    view = bh.parse(bytes(block), major=1, endian=endian)
    assert view["samples_per_trace"] == 1500
