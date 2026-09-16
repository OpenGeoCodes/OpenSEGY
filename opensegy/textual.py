"""Textual headers: the 3200-byte card image and its extended siblings.

Three things here are learned from real deliveries rather than from the
standard:

  * **The 3200 bytes are 40 cards of exactly 80 characters with no newlines.**
    A regex with `$` anchors run over the raw blob matches nothing and returns a
    confident "no map found". Always work on cards.
  * **The encoding is not stated anywhere.** The standard says EBCDIC, the world
    ships both, and cp037 and cp500 differ in punctuation that matters (`[`, `]`,
    `!`). So all candidates are tried and the one that yields the most printable
    text wins, with the decision recorded rather than assumed.
  * **A file can declare extended headers and not have them, or have them and
    not declare them.** Both happen. The count is read, and the bytes are
    checked against it.

Stanza *parsing* is not here; this module only recognises a stanza's opening
line, because that is what terminates a variable-length run of extended headers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .findings import Finding, info, warning

CARD_WIDTH = 80
CARDS_PER_HEADER = 40
TEXTUAL_HEADER_SIZE = CARD_WIDTH * CARDS_PER_HEADER   # 3200

#: Tried in this order; ties go to the earlier one. cp037 and cp500 are the two
#: EBCDIC code pages that seismic processors actually emit.
_ENCODINGS = ("cp037", "cp500", "ascii", "latin-1")

#: A stanza opens with a line like `((SEG: Layout 1.0))` or `((IOGP: P1/11))`.
#: Captured loosely on purpose: an unknown namespace is still a stanza, and
#: refusing to see it would be the one thing this library must never do.
STANZA_RE = re.compile(r"\(\(\s*(?P<namespace>[^:()]+?)\s*:\s*(?P<name>[^()]*?)\s*\)\)")

#: The stanza that ends a variable-length run of extended textual headers.
END_TEXT_RE = re.compile(r"\(\(\s*SEG\s*:\s*EndText\s*\)\)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TextualHeader:
    """One 3200-byte textual record, raw and decoded."""

    index: int                 # 0 = the mandatory header, 1..n = extended
    offset: int                # 1-based file byte where the record starts
    raw: bytes
    text: str                  # cards joined with newlines, trailing space kept out
    encoding: str
    printable_ratio: float

    @property
    def cards(self) -> list[str]:
        return self.text.split("\n")

    @property
    def is_extended(self) -> bool:
        return self.index > 0

    @property
    def stanza_label(self) -> str | None:
        """`"SEG: Layout 1.0"` when this record opens a stanza, else None."""
        m = STANZA_RE.search(self.text)
        if not m:
            return None
        return f"{m.group('namespace')}: {m.group('name')}".strip().rstrip(":").strip()

    @property
    def ends_text(self) -> bool:
        return bool(END_TEXT_RE.search(self.text))

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "offset": self.offset,
            "encoding": self.encoding,
            "printable_ratio": round(self.printable_ratio, 4),
            "stanza": self.stanza_label,
            "ends_text": self.ends_text,
            "text": self.text,
        }


def decode(raw: bytes) -> tuple[str, str, float]:
    """Decode a textual record, choosing the encoding by result.

    Returns the text cut into cards, the winning encoding, and the fraction of
    printable characters it achieved. That fraction is worth keeping: a header
    that decodes 0.55 printable is not a header, it is trace data being read at
    the wrong offset, and saying so is more useful than showing mojibake.
    """
    best: tuple[str, str, float] | None = None
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc, errors="replace")
        except LookupError:  # pragma: no cover - all four ship with CPython
            continue
        ratio = _card_ratio(text)
        if best is None or ratio > best[2]:
            best = (text, enc, ratio)
    assert best is not None
    text, enc, ratio = best
    return _to_cards(text), enc, ratio


def _card_ratio(text: str) -> float:
    """How much of this decodes to characters a punched card could hold.

    Two measurements were tried and discarded before this one, and both failures
    are worth recording because either would have moved where trace data starts:

      * `str.isprintable()` counts U+FFFD, which `errors="replace"` emits for
        every byte a codec cannot map. Random trace data scored 0.87 under ascii
        and ascii won the encoding contest for blocks that were not text at all.
      * Counting Unicode-printable characters still scored float trace data at
        0.82 under latin-1, which maps all 256 bytes and calls most of the upper
        half printable.

    Restricting the count to the ASCII printable range separates the two cleanly:
    real headers score 1.00, trace data in any sample format scores below 0.40.
    NUL is excluded from the denominator rather than counted against, because a
    header holding six cards of text and thirty-four cards of padding is still a
    header — and plenty of processors pad with NUL rather than with EBCDIC space.
    """
    considered = [ch for ch in text if ch != "\x00"]
    if not considered:
        return 0.0
    printable = sum(1 for ch in considered if " " <= ch <= "~" or ch == "\t")
    return printable / len(considered)


def _to_cards(text: str) -> str:
    lines = [text[i:i + CARD_WIDTH].rstrip()
             for i in range(0, len(text), CARD_WIDTH)]
    return "\n".join(lines).rstrip("\n")


def read_primary(source, *, offset: int = 0) -> TextualHeader:
    """The mandatory textual header, file bytes 1-3200."""
    raw = source.read(offset, TEXTUAL_HEADER_SIZE)
    text, enc, ratio = decode(raw)
    return TextualHeader(index=0, offset=offset + 1, raw=raw, text=text,
                         encoding=enc, printable_ratio=ratio)


def read_extended(source, *, declared: int | None, start_offset: int,
                  file_size: int | None = None,
                  max_scan: int = 1024) -> tuple[list[TextualHeader], list[Finding]]:
    """Read the extended textual headers that follow the binary header.

    `declared` is binary-header bytes 3505-3506:

        n > 0   exactly n records
        n == 0  none
        n == -1 a variable number, ending with the record that carries
                `((SEG: EndText))`
        None    the field was never written (rev 0), so none

    `max_scan` caps the variable-length walk so a corrupt count cannot turn into
    an unbounded read. Hitting the cap is a finding, not an exception.
    """
    out: list[TextualHeader] = []
    findings: list[Finding] = []

    if not declared:
        return out, findings

    limit = max_scan if declared == -1 else declared
    if declared == -1:
        findings.append(info(
            "textual.variable_extended_count",
            "The file declares a variable number of extended textual headers; "
            "reading until the end-text stanza.",
            byte_range=(3505, 3506)))

    offset = start_offset
    for i in range(1, limit + 1):
        if file_size is not None and offset + TEXTUAL_HEADER_SIZE > file_size:
            findings.append(warning(
                "textual.extended_truncated",
                f"The file declares {declared} extended textual header(s) but ends "
                f"after {len(out)}.",
                byte_range=(3505, 3506),
                evidence={"declared": declared, "found": len(out)}))
            break
        raw = source.read(offset, TEXTUAL_HEADER_SIZE)
        if len(raw) < TEXTUAL_HEADER_SIZE:
            findings.append(warning(
                "textual.extended_truncated",
                f"Extended textual header {i} is short: {len(raw)} bytes of "
                f"{TEXTUAL_HEADER_SIZE}.",
                evidence={"index": i, "bytes": len(raw)}))
            break
        text, enc, ratio = decode(raw)
        header = TextualHeader(index=i, offset=offset + 1, raw=raw, text=text,
                               encoding=enc, printable_ratio=ratio)
        out.append(header)
        offset += TEXTUAL_HEADER_SIZE
        if declared == -1 and header.ends_text:
            break
    else:
        if declared == -1:
            findings.append(warning(
                "textual.end_text_not_found",
                f"No end-text stanza was found within {max_scan} extended textual "
                "header records; where the trace data begins is unknown.",
                byte_range=(3505, 3506)))

    for h in out:
        label = h.stanza_label
        if label:
            findings.append(info(
                "textual.stanza_detected",
                f"Extended textual header {h.index} opens the stanza ({label}).",
                byte_range=(h.offset, h.offset + TEXTUAL_HEADER_SIZE - 1),
                evidence={"index": h.index, "stanza": label}))

    return out, findings


def check_primary(header: TextualHeader) -> list[Finding]:
    out: list[Finding] = []
    if header.printable_ratio < 0.85:
        out.append(warning(
            "textual.not_text",
            f"The first 3200 bytes decode to only "
            f"{header.printable_ratio:.0%} card characters, so they are "
            "probably not a textual header.",
            byte_range=(1, TEXTUAL_HEADER_SIZE),
            evidence={"printable_ratio": round(header.printable_ratio, 4),
                      "encoding": header.encoding}))
    return out


def sniff_undeclared(source, *, start_offset: int, file_size: int | None,
                     max_scan: int = 16) -> list[TextualHeader]:
    """Look for extended textual headers the binary header never declared.

    This happens, and when it does every trace in the file is read at the wrong
    offset with nothing to show for it. A 3200-byte record that decodes almost
    entirely to printable characters is not trace data; floating-point samples
    do not spell words. The threshold is deliberately high, because the cost of
    a false positive here is moving the start of the data.

    Whether anything is *done* with the answer is the caller's decision, and in
    `structure.scan` it is only acted on when the corrected offset divides the
    file into whole traces and the declared one does not.
    """
    found: list[TextualHeader] = []
    offset = start_offset
    for i in range(1, max_scan + 1):
        if file_size is not None and offset + TEXTUAL_HEADER_SIZE > file_size:
            break
        raw = source.read(offset, TEXTUAL_HEADER_SIZE)
        if len(raw) < TEXTUAL_HEADER_SIZE:
            break
        text, enc, ratio = decode(raw)
        looks_textual = ratio >= 0.95 or STANZA_RE.search(text) is not None
        if not looks_textual:
            break
        found.append(TextualHeader(index=i, offset=offset + 1, raw=raw, text=text,
                                   encoding=enc, printable_ratio=ratio))
        offset += TEXTUAL_HEADER_SIZE
    return found
