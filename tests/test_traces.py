"""Reading the samples, and reading every trace header without the samples."""
import numpy as np
import pytest

import opensegy
from opensegy.synthetic import SegyBuilder
from opensegy.traces import decode_samples
from opensegy.types import SAMPLE_DTYPE, Endian


def _file(**kw):
    n = kw.pop("n_samples", 24)
    b = SegyBuilder(samples_per_trace=n, **kw)
    b.add_grid(inlines=[10, 11, 12], crosslines=[100, 101, 102, 103])
    return b.build()


def test_a_trace_comes_back_as_float32_whatever_the_format_on_disk():
    for code in (1, 2, 3, 5, 6, 8):
        with opensegy.open(_file(sample_format=code)) as f:
            trace = f.trace(0)
            assert trace.dtype == np.float32
            assert trace.shape == (24,)


UNSIGNED_FORMATS = {10, 11, 12, 15, 16}


@pytest.mark.parametrize("code", sorted(SAMPLE_DTYPE))
@pytest.mark.parametrize("endian", [Endian.BIG, Endian.LITTLE])
def test_the_samples_written_are_the_samples_read(code, endian):
    values = [0.0, 1.0, 2.0, 3.0, 8.0, 16.0]
    if code not in UNSIGNED_FORMATS:
        values = values + [-1.0, -2.0]
    data = (SegyBuilder(sample_format=code, endian=endian,
                        samples_per_trace=len(values))
            .add_trace(samples=values).build())
    with opensegy.open(data) as f:
        assert f.trace(0) == pytest.approx(values, rel=1e-6)


@pytest.mark.parametrize("code", sorted(UNSIGNED_FORMATS))
def test_writing_a_negative_sample_to_an_unsigned_format_says_so(code):
    # Be strict when writing. The message must name the value and the field,
    # not leak a struct format character.
    with pytest.raises(ValueError, match="does not fit"):
        SegyBuilder(sample_format=code, samples_per_trace=1) \
            .add_trace(samples=[-1.0]).build()


def test_ibm_float_decodes_exactly_like_the_scalar_decoder():
    # The vectorised path is a different implementation; it must not be a
    # different answer.
    from opensegy.types import float_to_ibm32, ibm32_to_float
    values = [0.0, 1.0, -1.0, 118.625, 3.14159, -12345.678, 1e-5, 1e5]
    raw = b"".join(float_to_ibm32(v) for v in values)
    assert decode_samples(raw, 1) == pytest.approx(
        [ibm32_to_float(raw[i * 4:i * 4 + 4]) for i in range(len(values))])


def test_three_byte_integers_round_trip_in_both_byte_orders():
    # Rev 2 added 24-bit samples and numpy has no dtype for them.
    for endian in (Endian.BIG, Endian.LITTLE):
        for code in (7, 15):
            values = [0.0, 1.0, 100.0, 8_388_607.0] if code == 15 else \
                     [0.0, 1.0, -1.0, -8_388_608.0]
            data = (SegyBuilder(sample_format=code, endian=endian,
                                samples_per_trace=len(values))
                    .add_trace(samples=values).build())
            with opensegy.open(data) as f:
                assert f.trace(0) == pytest.approx(values)


def test_a_bulk_read_equals_reading_one_trace_at_a_time():
    with opensegy.open(_file(sample_format=1)) as f:
        one_by_one = np.stack([f.trace(i) for i in range(f.n_traces)])
        assert np.array_equal(f.traces(), one_by_one)
        assert np.array_equal(f[2:5], one_by_one[2:5])


def test_indexing_and_iteration():
    with opensegy.open(_file()) as f:
        assert len(f) == 12
        assert np.array_equal(f[0], f.trace(0))
        assert np.array_equal(f[-1], f.trace(11))
        assert sum(1 for _ in f) == 12


def test_an_out_of_range_trace_raises_rather_than_reading_rubbish():
    with opensegy.open(_file()) as f:
        with pytest.raises(IndexError):
            f.trace(12)


def test_header_table_gives_the_geometry_without_touching_a_sample():
    with opensegy.open(_file()) as f:
        table = f.header_table(["inline", "crossline", "coordinate_scalar"])
        assert list(table["inline"]) == [10] * 4 + [11] * 4 + [12] * 4
        assert list(table["crossline"]) == [100, 101, 102, 103] * 3
        assert set(table["coordinate_scalar"]) == {-100}


def test_header_table_can_step_through_a_file():
    with opensegy.open(_file()) as f:
        assert list(f.header_table(["crossline"], step=4)["crossline"]) == [100, 100, 100]
        assert list(f.header_table(["inline"], start=4, stop=8)["inline"]) == [11] * 4


def test_an_unknown_field_name_is_refused_by_name():
    with opensegy.open(_file()) as f:
        with pytest.raises(KeyError):
            f.header_table(["not_a_field"])


def test_headers_read_the_same_in_bulk_as_one_at_a_time():
    with opensegy.open(_file()) as f:
        table = f.header_table(["inline", "crossline"])
        for i in range(f.n_traces):
            view = f.header(i)
            assert (view["inline"], view["crossline"]) == (
                table["inline"][i], table["crossline"][i])


def test_extended_textual_headers_do_not_displace_the_traces():
    # The whole point, checked through the reading API rather than the structure.
    plain = _file(sample_format=1)
    shifted = _file(sample_format=1, extended_textual=["ONE", "TWO", "THREE"])
    with opensegy.open(plain) as a, opensegy.open(shifted) as b:
        assert b.structure.data_start == 3600 + 3 * 3200
        assert np.array_equal(a.traces(), b.traces())


def test_rev2_trace_header_extensions_are_read_and_do_not_corrupt_the_samples():
    data = (SegyBuilder(revision=(2, 1), extra_trace_headers=2, samples_per_trace=16)
            .add_trace(samples=[1.0] * 16,
                       extensions=[{"trace_header_name": "VENDOR01"},
                                   {"trace_header_name": "VENDOR02"}])
            .build())
    with opensegy.open(data) as f:
        assert f.trace(0) == pytest.approx([1.0] * 16)
        names = [v["trace_header_name"] for v in f.header_extensions(0)]
        assert names == ["VENDOR01", "VENDOR02"]


def test_a_variable_length_file_refuses_to_index_rather_than_guess():
    b = SegyBuilder(revision=(1, 0), fixed_length=False)
    for n in (10, 20, 30):
        b.add_trace(samples=[0.0] * n)
    with opensegy.open(b.build()) as f:
        with pytest.raises(ValueError):
            f.n_traces


def test_a_partial_trailing_trace_is_excluded_and_reported():
    whole = _file(sample_format=5)
    with opensegy.open(whole) as f:
        full_count = f.n_traces
    with opensegy.open(whole[:-40]) as f:
        assert f.n_traces == full_count - 1        # the partial one is not a trace
        assert "structure.trailing_bytes" in {x.code for x in f.findings}
        assert f.trace(f.n_traces - 1).shape == (24,)   # the last whole one reads


def test_a_source_that_returns_short_data_raises_rather_than_padding():
    from opensegy.source import MemorySource

    class Truncating(MemorySource):
        def read(self, offset, length):
            return super().read(offset, length)[:length // 2]

    data = _file(sample_format=5)
    with opensegy.open(data) as good:
        n = good.n_traces
    f = opensegy.SegyFile(structure=opensegy.scan(data), source=Truncating(data))
    with pytest.raises(EOFError):
        f.trace(n - 1)


def test_an_ibm_zero_written_with_a_large_exponent_is_still_zero():
    # IBM floats are not normalised, so a word with a big exponent and a zero
    # mantissa is an ordinary way of writing zero, and real files contain them.
    # The lookup table the fast path uses must be clipped to a finite float32,
    # or that zero becomes 0 * inf, which is NaN.
    from opensegy.traces import decode_samples
    from opensegy.types import ibm32_to_float
    for word in (0x00000000, 0x40000000, 0x7F000000, 0xFF000000):
        raw = word.to_bytes(4, "big")
        assert decode_samples(raw, 1)[0] == ibm32_to_float(raw)
        assert not np.isnan(decode_samples(raw, 1)[0])


def test_the_ibm_scale_table_holds_no_infinities():
    from opensegy.traces import _IBM_SCALE
    assert np.isfinite(_IBM_SCALE).all()
    assert len(_IBM_SCALE) == 256


def test_vectorised_ibm_matches_the_scalar_decoder_across_six_orders_of_magnitude():
    from opensegy.traces import decode_samples
    from opensegy.types import float_to_ibm32, ibm32_to_float
    rng = np.random.default_rng(7)
    values = np.concatenate([rng.normal(scale=s, size=2000)
                             for s in (1e-6, 1.0, 1e3, 1e6)])
    raw = b"".join(float_to_ibm32(float(v)) for v in values)
    vectorised = decode_samples(raw, 1)
    scalar = np.array([ibm32_to_float(raw[i * 4:i * 4 + 4])
                       for i in range(len(values))], dtype=np.float32)
    assert np.array_equal(vectorised, scalar)
