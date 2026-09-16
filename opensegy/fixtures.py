"""A standard set of SEG-Y files to test readers against, this one included.

Generated rather than checked in. A binary fixture in a repository is a fact
nobody can read in a diff and nobody dares change; a builder call is a sentence
that says what the file is. It also means the set can be written to disk and
handed to *another* tool, which is how a question like "does OpenVDS SEGYImport
handle revision 2 at all?" gets an answer.

    python -m opensegy fixtures ./segy-fixtures
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .synthetic import SegyBuilder
from .types import Endian

_LAYOUT_STANZA = (
    "((SEG: Layout 1.0))\n"
    '<CTF xmlns="http://www.seg.org/SEG-Y/2.1/Layout">\n'
    '  <entry name="iline"  byte="189" type="int4"/>\n'
    '  <entry name="xline"  byte="193" type="int4"/>\n'
    '  <entry name="cdp_x"  byte="181" type="int4"/>\n'
    '  <entry name="cdp_y"  byte="185" type="int4"/>\n'
    "</CTF>"
)

_HISTORY_STANZA = (
    "((SEG: Processing History 1.0))\n"
    "Processing Company: OPENSEGY SYNTHETIC\n"
    "Process Applied: SC Decon\n"
    "Process Applied: Kirchhoff PSTM\n"
)


def _small(builder: SegyBuilder) -> SegyBuilder:
    return builder.add_grid(inlines=range(100, 106), crosslines=range(200, 212))


#: name → a callable returning the file's bytes. Names are also filenames.
FIXTURES: dict[str, Callable[[], bytes]] = {
    # rev0
    "rev0/minimal": lambda: _small(SegyBuilder(revision=(0, 0), sample_format=1)).build(),
    # rev1
    "rev1/ibm_float": lambda: _small(SegyBuilder(revision=(1, 0), sample_format=1)).build(),
    "rev1/ieee_float": lambda: _small(SegyBuilder(revision=(1, 0), sample_format=5)).build(),
    "rev1/two_extended_textual_headers": lambda: _small(SegyBuilder(
        revision=(1, 0),
        extended_textual=["EXTENDED HEADER ONE", "EXTENDED HEADER TWO"])).build(),
    # rev2
    "rev2/big_endian": lambda: _small(SegyBuilder(revision=(2, 0))).build(),
    "rev2/little_endian": lambda: _small(SegyBuilder(
        revision=(2, 0), endian=Endian.LITTLE)).build(),
    "rev2/float64_samples": lambda: _small(SegyBuilder(
        revision=(2, 0), sample_format=6, samples_per_trace=32)).build(),
    "rev2/variable_extended_count": lambda: _small(SegyBuilder(
        revision=(2, 0), extended_textual=[_LAYOUT_STANZA],
        declared_extended_count=-1)).build(),
    # rev2.1
    "rev21/layout_stanza": lambda: _small(SegyBuilder(
        revision=(2, 1), survey_type=3,
        extended_textual=[_LAYOUT_STANZA])).build(),
    "rev21/processing_history": lambda: _small(SegyBuilder(
        revision=(2, 1), survey_type=3,
        extended_textual=[_LAYOUT_STANZA, _HISTORY_STANZA])).build(),
    "rev21/trace_header_extensions": lambda: _small(SegyBuilder(
        revision=(2, 1), survey_type=3, extra_trace_headers=2)).build(),
    "rev21/data_trailer": lambda: _small(SegyBuilder(
        revision=(2, 1), survey_type=3,
        data_trailer=["((SEG: Trailer))\nTRAILING METADATA"])).build(),
    # broken: each one is a bug a reader should notice, not a file it should refuse
    "broken/declares_rev1_carries_rev2": lambda: _small(SegyBuilder(
        revision=(2, 0), declared_revision=(1, 0))).build(),
    "broken/byte_swapped_revision": lambda: _swap_revision(
        _small(SegyBuilder(revision=(1, 0))).build()),
    "broken/undeclared_extended_headers": lambda: _small(SegyBuilder(
        revision=(1, 0), extended_textual=["UNDECLARED ONE", "UNDECLARED TWO"],
        declared_extended_count=0)).build(),
    "broken/trace_count_lies": lambda: _small(SegyBuilder(
        revision=(2, 0), declared_trace_count=999_999)).build(),
    "broken/first_trace_offset_lies": lambda: _small(SegyBuilder(
        revision=(2, 0), extended_textual=["ONE"],
        declared_first_trace_offset=3600)).build(),
    "broken/variable_trace_length": lambda: _variable_length(),
    "broken/truncated_mid_trace": lambda: _small(
        SegyBuilder(revision=(1, 0))).build()[:-137],
}


def _swap_revision(data: bytes) -> bytes:
    out = bytearray(data)
    out[3500:3502] = b"\x00\x01"
    return bytes(out)


def _variable_length() -> bytes:
    b = SegyBuilder(revision=(1, 0), fixed_length=False)
    for n in (40, 55, 33, 40, 61):
        b.add_trace(samples=[0.0] * n)
    return b.build()


def materialise(directory: str | Path, *, suffix: str = ".sgy") -> list[Path]:
    """Write every fixture under `directory`, creating the subfolders."""
    root = Path(directory)
    written: list[Path] = []
    for name, build in FIXTURES.items():
        path = root / f"{name}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(build())
        written.append(path)
    return written
