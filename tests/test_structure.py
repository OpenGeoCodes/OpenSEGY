"""The acceptance criteria for stage 1 live here.

Every test states a behaviour a SEG-Y reader must have and that the readers this
library replaces did not.
"""
import pytest

from opensegy import scan
from opensegy.structure import read_declared_revision
from opensegy.synthetic import SegyBuilder
from opensegy.types import Endian


def _grid(**kw):
    b = SegyBuilder(**kw)
    b.add_grid(inlines=range(1, 4), crosslines=range(1, 5))
    return b.build()


def _codes(segy):
    return {f.code for f in segy.findings}


# ── the bug this library exists to remove ────────────────────────────────────

def test_extended_textual_headers_move_where_the_traces_begin():
    # The standard has allowed these since rev 1. A reader that seeks to 3600
    # reads every trace 6400 bytes out of position and reports nothing.
    segy = scan(_grid(revision=(1, 0), extended_textual=["FIRST", "SECOND"]))
    assert segy.data_start == 3600 + 2 * 3200
    assert segy.data_start_source == "counted_extended_textual_headers"
    assert segy.trace_count == 12
    assert len(segy.extended_textual) == 2


def test_a_file_with_no_extended_headers_still_starts_at_3600():
    segy = scan(_grid(revision=(1, 0)))
    assert segy.data_start == 3600
    assert segy.trace_count == 12
    assert segy.findings == []


def test_a_variable_length_run_ends_at_the_end_text_stanza():
    data = _grid(revision=(2, 0), extended_textual=["ONE", "TWO"],
                 declared_extended_count=-1)
    segy = scan(data)
    assert len(segy.extended_textual) == 3          # the two, plus EndText
    assert segy.extended_textual[-1].ends_text
    assert segy.data_start == 3600 + 3 * 3200
    assert segy.trace_count == 12


def test_undeclared_extended_headers_are_rescued_only_when_arithmetic_proves_it():
    # Declares none, carries two. The rescue is allowed because the corrected
    # offset divides the file into whole traces and 3600 does not.
    segy = scan(_grid(revision=(1, 0), extended_textual=["A", "B"],
                      declared_extended_count=0))
    assert segy.data_start == 3600 + 2 * 3200
    assert segy.trace_count == 12
    assert "structure.undeclared_extended_textual_headers" in _codes(segy)


# ── revision ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("revision", [(0, 0), (1, 0), (2, 0), (2, 1)])
def test_a_correctly_declared_revision_is_read_back(revision):
    segy = scan(_grid(revision=revision))
    assert segy.declared_revision == revision
    assert segy.revision >= revision


def test_declaring_rev1_while_carrying_rev2_structures_is_a_warning():
    segy = scan(_grid(revision=(2, 0), declared_revision=(1, 0)))
    assert segy.declared_revision == (1, 0)
    assert segy.detected_revision == (2, 0)
    assert segy.revision == (2, 0)          # the structure wins
    assert "revision.declared_below_structure" in _codes(segy)


def test_the_signals_behind_a_detected_revision_are_reported():
    segy = scan(_grid(revision=(2, 0), declared_revision=(1, 0)))
    names = {s.name for s in segy.revision_signals}
    assert "byte_order_constant" in names
    assert all(s.byte_range for s in segy.revision_signals)


def test_revision_0_1_is_recognised_as_a_byte_swapped_1_0():
    # No SEG-Y revision defines 0.1. Vendors write it by putting the rev 1
    # int16 the wrong way round.
    data = bytearray(_grid(revision=(1, 0)))
    data[3500:3502] = b"\x00\x01"
    revision, findings = read_declared_revision(bytes(data[3200:3600]))
    assert revision == (1, 0)
    assert findings[0].code == "revision.byte_swapped"
    assert findings[0].byte_range == (3501, 3502)


def test_a_revision_newer_than_the_library_is_a_warning_not_a_refusal():
    data = bytearray(_grid(revision=(2, 1)))
    data[3500:3502] = b"\x09\x00"
    segy = scan(bytes(data))
    assert "revision.unknown" in _codes(segy)
    assert segy.trace_count == 12          # still read


# ── byte order ───────────────────────────────────────────────────────────────

def test_little_endian_is_read_from_the_rev2_constant():
    segy = scan(_grid(revision=(2, 0), endian=Endian.LITTLE))
    assert segy.endian is Endian.LITTLE
    assert segy.endian_source == "rev2_constant"
    assert segy.sample_count == 51
    assert segy.trace_count == 12


def test_a_pre_rev2_file_falls_back_to_plausibility():
    segy = scan(_grid(revision=(1, 0)))
    assert segy.endian is Endian.BIG
    assert segy.endian_source == "plausibility"


def test_the_byte_order_constant_is_not_written_when_asked_not_to():
    segy = scan(_grid(revision=(2, 0), write_byte_order_constant=False))
    assert segy.endian_source != "rev2_constant"
    assert segy.trace_count == 12


# ── trace geometry ───────────────────────────────────────────────────────────

def test_trace_stride_accounts_for_the_sample_format():
    segy = scan(_grid(revision=(1, 0), sample_format=3, samples_per_trace=100))
    assert segy.sample_bytes == 2
    assert segy.trace_bytes == 240 + 100 * 2
    assert segy.trace_offset(0) == 3600
    assert segy.trace_offset(5) == 3600 + 5 * segy.trace_bytes


def test_extra_trace_headers_widen_the_stride_and_are_flagged_as_an_assumption():
    # The standard gives a maximum, not a count, so a uniform stride is an
    # assumption. It is recorded as one and still used, because refusing would
    # make rev 2 extensions unreadable for the files that actually carry them.
    segy = scan(_grid(revision=(2, 1), extra_trace_headers=2))
    assert segy.extra_trace_headers == 2
    assert segy.trace_bytes == 240 * 3 + 51 * 4
    assert segy.trace_stride_certain is False
    assert "structure.extra_trace_headers_assumed_uniform" in _codes(segy)
    assert segy.trace_offset(1) == segy.data_start + segy.trace_bytes


def test_variable_length_is_the_one_case_that_refuses_an_index():
    b = SegyBuilder(revision=(1, 0), fixed_length=False)
    for n in (10, 20):
        b.add_trace(samples=[0.0] * n)
    with pytest.raises(ValueError, match="vary in length"):
        scan(b.build()).trace_offset(1)


def test_variable_trace_length_refuses_to_pretend_an_index_works():
    b = SegyBuilder(revision=(1, 0), fixed_length=False)
    for n in (40, 55, 33, 40):
        b.add_trace(samples=[0.0] * n)
    segy = scan(b.build())
    assert segy.fixed_length is False
    assert segy.trace_stride_certain is False
    assert segy.trace_count is None
    assert "structure.variable_trace_length" in _codes(segy)


def test_a_declared_trace_count_that_the_file_size_contradicts_is_reported():
    segy = scan(_grid(revision=(2, 0), declared_trace_count=999))
    assert segy.trace_count == 999
    assert segy.trace_count_source == "declared"
    assert "structure.trace_count_disagrees" in _codes(segy)


def test_a_declared_first_trace_offset_loses_to_arithmetic():
    # Bytes 3521-3528 say 3600; only 6800 divides the file into whole traces.
    segy = scan(_grid(revision=(2, 0), extended_textual=["X"],
                      declared_first_trace_offset=3600))
    assert segy.data_start == 6800
    assert "structure.data_start_disagrees" in _codes(segy)


def test_a_declared_first_trace_offset_that_agrees_is_recorded_as_agreeing():
    segy = scan(_grid(revision=(2, 0), extended_textual=["X"]))
    assert segy.data_start == 6800
    assert segy.data_start_source == "declared_and_counted_agree"


# ── robustness ───────────────────────────────────────────────────────────────

def test_a_file_too_short_to_hold_a_binary_header_is_described_not_raised():
    segy = scan(b"\x40" * 3000)
    assert "structure.binary_header_missing" in _codes(segy)
    assert segy.severity.value == "error"


def test_trailing_bytes_after_the_last_trace_are_reported():
    data = _grid(revision=(1, 0)) + b"\x00" * 17
    segy = scan(data)
    assert "structure.trailing_bytes" in _codes(segy)


def test_a_declared_data_trailer_is_not_counted_as_traces():
    # Rev 2 allows 3200-byte records after the last trace. Counting them is how
    # a correct file acquires a spurious trailing-bytes warning and a trace
    # count several too high.
    segy = scan(_grid(revision=(2, 0),
                      data_trailer=["((SEG: Trailer))", "MORE TRAILER"]))
    assert segy.trailer_records == 2
    assert segy.data_end == segy.file_size - 2 * 3200
    assert segy.trace_count == 12
    assert "structure.trailing_bytes" not in _codes(segy)
    assert "structure.data_trailer" in _codes(segy)


def test_a_variable_length_data_trailer_says_it_cannot_measure_it_yet():
    data = bytearray(_grid(revision=(2, 0)))
    data[3528:3532] = (-1).to_bytes(4, "big", signed=True)
    segy = scan(bytes(data))
    assert "structure.variable_data_trailer" in _codes(segy)


def test_the_whole_structure_serialises_to_json_safe_types():
    import json
    segy = scan(_grid(revision=(2, 1), extended_textual=["((SEG: Layout 1.0))"]))
    blob = json.dumps(segy.to_dict())
    assert '"used": "2.1"' in blob
    assert "byte_range" in blob
