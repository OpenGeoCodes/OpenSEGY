import pytest

from opensegy import scan
from opensegy.synthetic import SegyBuilder
from opensegy.trace_header import TRACE_HEADER_SIZE, parse
from opensegy.types import SAMPLE_BYTES, SAMPLE_DTYPE, Endian, decode_scalar


def test_a_builder_left_alone_produces_a_file_with_nothing_wrong_with_it():
    # Defaults are always truthful; every lie is a named knob.
    segy = scan(SegyBuilder().add_grid(inlines=range(1, 3),
                                       crosslines=range(1, 3)).build())
    assert segy.findings == []


@pytest.mark.parametrize("code", sorted(SAMPLE_DTYPE))
def test_every_sample_format_can_be_written_and_measured_back(code):
    n = 8
    data = (SegyBuilder(sample_format=code, samples_per_trace=n)
            .add_trace(samples=[1.0] * n).build())
    segy = scan(data)
    assert segy.sample_bytes == SAMPLE_BYTES[code]
    assert segy.trace_bytes == 240 + n * SAMPLE_BYTES[code]
    assert segy.trace_count == 1


@pytest.mark.parametrize("code", [1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 16])
def test_sample_values_survive_the_round_trip(code):
    values = [1.0, 2.0, 3.0, 4.0]
    data = (SegyBuilder(sample_format=code, samples_per_trace=len(values))
            .add_trace(samples=values).build())
    segy = scan(data)
    dtype = SAMPLE_DTYPE[code]
    width = SAMPLE_BYTES[code]
    start = segy.data_start + TRACE_HEADER_SIZE
    read = [decode_scalar(data[start + i * width:start + (i + 1) * width], dtype)
            for i in range(len(values))]
    assert read == pytest.approx(values)


def test_the_grid_helper_writes_coordinates_on_a_lattice():
    data = (SegyBuilder()
            .add_grid(inlines=[1, 2], crosslines=[1, 2, 3],
                      origin=(400000.0, 7000000.0), bin_size=(25.0, 12.5))
            .build())
    segy = scan(data)
    def header(i):
        off = segy.data_start + i * segy.trace_bytes
        return parse(data[off:off + TRACE_HEADER_SIZE], offset=off)
    first, second = header(0), header(1)
    assert second["cdp_x"] - first["cdp_x"] == 2500      # 25 m at scalar -100
    fourth = header(3)                                   # next inline
    assert fourth["cdp_y"] - first["cdp_y"] == 1250      # 12.5 m


def test_the_builder_writes_what_the_reader_reads_through():
    # Writer and reader share one field table, so a fixture cannot drift from
    # the parser that is supposed to check it.
    from opensegy import binary_header as bh
    data = SegyBuilder(revision=(2, 1), survey_type=3, sample_format=5,
                       sample_interval_us=2000, samples_per_trace=1500,
                       measurement_system=2).add_trace().build()
    view = bh.parse(data[3200:3600], major=2, minor=1)
    assert view["survey_type"] == 3
    assert view["sample_interval"] == 2000
    assert view["samples_per_trace"] == 1500
    assert view.reading("measurement_system").interpretation == "feet"


def test_a_file_can_be_written_to_disk_and_read_from_the_path(tmp_path):
    path = tmp_path / "synthetic.sgy"
    SegyBuilder().add_grid(inlines=range(1, 3), crosslines=range(1, 4)).write(path)
    segy = scan(str(path))
    assert segy.trace_count == 6
    assert segy.file_size == path.stat().st_size


def test_bytes_a_path_and_a_custom_source_all_work():
    from opensegy.source import MemorySource
    data = SegyBuilder().add_trace().build()
    assert scan(data).trace_count == scan(MemorySource(data)).trace_count == 1


def test_an_unknown_sample_format_is_refused_when_writing():
    # Be strict when writing, tolerant when reading.
    with pytest.raises(ValueError):
        SegyBuilder(sample_format=77)


@pytest.mark.parametrize("endian", [Endian.BIG, Endian.LITTLE])
@pytest.mark.parametrize("revision", [(0, 0), (1, 0), (2, 0), (2, 1)])
def test_the_matrix_of_revisions_and_byte_orders_round_trips(revision, endian):
    data = (SegyBuilder(revision=revision, endian=endian, samples_per_trace=16)
            .add_grid(inlines=range(1, 3), crosslines=range(1, 3)).build())
    segy = scan(data)
    assert segy.trace_count == 4
    assert segy.sample_count == 16
    assert segy.revision >= revision
