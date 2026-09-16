import pytest

from opensegy import scan
from opensegy.synthetic import SegyBuilder, default_textual
from opensegy.textual import (
    CARD_WIDTH,
    STANZA_RE,
    TEXTUAL_HEADER_SIZE,
    decode,
    read_primary,
)
from opensegy.source import MemorySource


def _header(text, encoding="cp037"):
    return text.ljust(TEXTUAL_HEADER_SIZE)[:TEXTUAL_HEADER_SIZE].encode(encoding)


def test_the_encoding_is_chosen_by_result_not_assumed():
    for encoding in ("cp037", "cp500", "ascii"):
        text, chosen, ratio = decode(_header("C 1 CLIENT ANP", encoding))
        assert text.startswith("C 1 CLIENT ANP")
        assert ratio > 0.99
        assert chosen in ("cp037", "cp500", "ascii", "latin-1")


def test_the_3200_bytes_are_cut_into_80_column_cards():
    # There are no newlines in the file. A regex anchored on line ends matches
    # nothing against the raw blob and returns a confident "nothing found".
    raw = _header("".join(f"C{i:2d} LINE {i}".ljust(CARD_WIDTH) for i in range(1, 41)))
    text, _, _ = decode(raw)
    cards = text.split("\n")
    assert len(cards) == 40
    assert cards[0].startswith("C 1 LINE 1")
    assert cards[39].startswith("C40 LINE 40")


@pytest.mark.parametrize("fmt", ["ieee32", "ibm32", "int16"])
def test_trace_data_read_as_a_header_is_recognised_as_not_text(fmt):
    # If this ever stops holding, the undeclared-extended-header rescue could
    # move where the trace data starts on a false positive.
    from opensegy.synthetic import _ricker
    from opensegy.textual import check_primary
    from opensegy.types import encode_scalar
    samples = _ricker(800) if fmt != "int16" else [int(v * 1000) for v in _ricker(1600)]
    raw = b"".join(encode_scalar(v, fmt) for v in samples)[:TEXTUAL_HEADER_SIZE]
    header = read_primary(MemorySource(raw.ljust(TEXTUAL_HEADER_SIZE, b"\x11")))
    assert header.printable_ratio < 0.5
    assert check_primary(header)[0].code == "textual.not_text"


def test_a_header_padded_with_nulls_is_still_a_header():
    # Plenty of processors pad with NUL rather than with EBCDIC space. Counting
    # the padding against the score would call a real header binary.
    raw = default_textual()[:480].encode("cp037").ljust(TEXTUAL_HEADER_SIZE, b"\x00")
    header = read_primary(MemorySource(raw))
    assert header.printable_ratio == 1.0
    from opensegy.textual import check_primary
    assert check_primary(header) == []


def test_a_stanza_opening_line_is_recognised_whatever_the_namespace():
    for line, namespace in [("((SEG: Layout 1.0))", "SEG"),
                            ("((IOGP: P1/11))", "IOGP"),
                            ("((Acme: Whatever 3))", "Acme")]:
        match = STANZA_RE.search(line)
        assert match and match.group("namespace") == namespace


def test_an_unknown_stanza_is_preserved_and_named():
    # Never reject a stanza for being unrecognised. Preserve it.
    data = (SegyBuilder(revision=(2, 1),
                        extended_textual=["((Acme: SecretSauce 9.9))\nWHATEVER"])
            .add_trace().build())
    segy = scan(data)
    stanza = segy.extended_textual[0]
    assert stanza.stanza_label == "Acme: SecretSauce 9.9"
    assert "WHATEVER" in stanza.text
    assert len(stanza.raw) == TEXTUAL_HEADER_SIZE


def test_the_raw_bytes_of_every_textual_record_are_kept():
    data = (SegyBuilder(revision=(1, 0), extended_textual=["ONE", "TWO"])
            .add_trace().build())
    segy = scan(data)
    assert len(segy.primary_textual.raw) == TEXTUAL_HEADER_SIZE
    assert all(len(h.raw) == TEXTUAL_HEADER_SIZE for h in segy.extended_textual)


def test_declared_extended_headers_that_are_not_there_are_reported():
    data = (SegyBuilder(revision=(1, 0), declared_extended_count=4)
            .add_trace().build())
    segy = scan(data)
    assert "textual.extended_truncated" in {f.code for f in segy.findings}


def test_the_default_textual_header_is_forty_cards():
    assert len(default_textual()) == TEXTUAL_HEADER_SIZE
