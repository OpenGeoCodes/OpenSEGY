import pytest

from opensegy import apply_coordinate_scalar, scan
from opensegy.synthetic import SegyBuilder
from opensegy.trace_header import TRACE_HEADER_SIZE, fields_for, parse, parse_trace
from opensegy.types import Endian, encode_scalar


def _block(**values):
    blk = bytearray(TRACE_HEADER_SIZE)
    table = {f.name: f for f in fields_for()}
    for name, value in values.items():
        fd = table[name]
        blk[fd.start - 1:fd.start - 1 + fd.width] = encode_scalar(value, fd.dtype)
    return bytes(blk)


def test_a_trace_header_field_reports_its_absolute_file_position():
    view = parse(_block(inline=1256), offset=3600)
    reading = view.reading("inline")
    assert reading.byte_range == (3789, 3792)      # 3600 + 189 .. 3600 + 192
    assert reading.value == 1256


def test_any_byte_can_be_asked_which_field_covers_it():
    view = parse(_block(crossline=42), offset=3600)
    assert view.at(3793).name == "crossline"
    assert view.at(3600 + 240) is None


@pytest.mark.parametrize("scalar,raw,expected", [
    (-100, 57012345, 570123.45),       # negative divides
    (100, 5701, 570100.0),             # positive multiplies
    (0, 570123, 570123.0),             # zero means no scaling
    (None, 570123, 570123.0),
])
def test_the_coordinate_scalar_convention(scalar, raw, expected):
    assert apply_coordinate_scalar(raw, scalar) == pytest.approx(expected)


def test_240_bytes_is_the_first_trace_header_not_the_whole_of_it():
    # Rev 2 allows additional headers, each named in its last eight bytes.
    blocks = [_block(inline=10), bytes(232) + b"VENDOR01"]
    views = parse_trace(blocks, major=2, minor=1, offset=3600)
    assert len(views) == 2
    assert views[0]["inline"] == 10
    assert views[1]["trace_header_name"] == "VENDOR01"
    # The name sits at bytes 233-240 of the *second* block, so 3600 + 240 + 232.
    assert views[1].reading("trace_header_name").byte_range == (4073, 4080)


def test_extension_blocks_are_addressed_from_their_own_offset():
    blocks = [_block(), bytes(232) + b"EXT00001"]
    views = parse_trace(blocks, major=2, minor=1, offset=10000)
    # block_offset is the 1-based file byte the block starts at.
    assert views[1].block_offset == 10001 + TRACE_HEADER_SIZE


def test_a_built_file_reads_its_trace_headers_back():
    data = (SegyBuilder(revision=(1, 0))
            .add_grid(inlines=[100, 101], crosslines=[200, 201, 202])
            .build())
    segy = scan(data)
    first = parse(data[segy.data_start:segy.data_start + TRACE_HEADER_SIZE],
                  offset=segy.data_start)
    assert (first["inline"], first["crossline"]) == (100, 200)
    assert apply_coordinate_scalar(first["cdp_x"], first["coordinate_scalar"]) == 500000.0


def test_trace_headers_read_back_in_little_endian_too():
    data = (SegyBuilder(revision=(2, 0), endian=Endian.LITTLE)
            .add_grid(inlines=[7], crosslines=[9]).build())
    segy = scan(data)
    view = parse(data[segy.data_start:segy.data_start + TRACE_HEADER_SIZE],
                 endian=segy.endian, offset=segy.data_start)
    assert (view["inline"], view["crossline"]) == (7, 9)


def test_a_rev0_file_that_carries_an_inline_is_still_read():
    # Half the deliveries that declare rev 0 carry an inline at byte 189 anyway,
    # because the processor wrote one. Refusing on the strength of two bytes at
    # 3501 would be the same mistake as trusting them for anything else.
    from opensegy.traces import open as open_segy
    data = (SegyBuilder(revision=(0, 0))
            .add_grid(inlines=[500, 501], crosslines=[10, 11]).build())
    with open_segy(data) as f:
        assert f.structure.declared_revision == (0, 0)
        assert list(f.header_table(["inline"])["inline"]) == [500, 500, 501, 501]


def test_only_defined_restricts_the_table_for_a_validator():
    assert len(fields_for(0, 0, only_defined=True)) == 71
    assert len(fields_for(1, 0, only_defined=True)) == 89
    assert len(fields_for()) == 89
