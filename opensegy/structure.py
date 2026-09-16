"""Where everything is: revision, byte order, and the offset of the first trace.

This is the module the rest of OpenSEGY depends on, because almost every other
question is downstream of three answers:

    which revision's field table applies,
    which way round the integers are,
    where the trace data actually starts.

None of the three can be taken from the file's own word alone.

**Revision.** The declared revision is two bytes that vendors have been writing
wrongly for twenty years. So it is read *and* the structure is examined, and the
two answers are reported separately. The platform this library came from had
dismissed the field as "useless"; the fix is not to ignore it but to stop
treating it as the only witness.

**Byte order.** Rev 2 added a known constant at 3297-3300 precisely so this
stops being a guess. Before rev 2 there is no such constant, and the only
honest method is to read the sample format and geometry both ways and see which
one is not nonsense.

**Data start.** Every reader in the platform assumed 3600. That is correct only
when there are no extended textual headers, and the standard has permitted them
since rev 1. A file with two of them read at 3600 yields traces displaced by
6400 bytes, with no error anywhere — the single most consequential bug this
library exists to remove.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import binary_header as bh
from . import textual
from .fields import HeaderView
from .findings import Finding, Severity, error, info, warning, worst
from .source import as_source
from .types import (
    BYTE_ORDER_CONSTANT,
    BYTE_ORDER_PAIRWISE,
    BYTE_ORDER_REVERSED,
    SAMPLE_BYTES,
    SAMPLE_FORMAT_NAMES,
    SAMPLE_FORMAT_SINCE,
    Endian,
    decode_scalar,
)

#: Envelope used only to judge a guess, never to reject a file. A record shorter
#: than 8 samples or longer than a million is not impossible, it is just not what
#: a correctly-read header looks like.
_PLAUSIBLE_SAMPLES = (1, 1_000_000)


@dataclass(frozen=True, slots=True)
class RevisionSignal:
    """One structural reason to believe a file is at least revision X."""

    name: str
    implies: tuple[int, int]
    strength: str          # "strong" | "moderate" | "weak"
    detail: str
    byte_range: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "implies": f"{self.implies[0]}.{self.implies[1]}",
            "strength": self.strength,
            "detail": self.detail,
            "byte_range": list(self.byte_range) if self.byte_range else None,
        }


@dataclass
class SegyStructure:
    """The shape of a SEG-Y file, with every answer traceable to its bytes."""

    declared_revision: tuple[int, int]
    detected_revision: tuple[int, int]
    revision_signals: list[RevisionSignal]
    endian: Endian
    endian_source: str

    binary: HeaderView
    primary_textual: textual.TextualHeader
    extended_textual: list[textual.TextualHeader]

    data_start: int              # 0-based byte offset of the first trace
    data_start_source: str
    sample_count: int | None
    sample_count_source: str
    sample_interval: float | None
    sample_format: int | None
    sample_bytes: int | None
    extra_trace_headers: int
    trace_bytes: int | None
    trace_stride_certain: bool
    fixed_length: bool | None
    trace_count: int | None
    trace_count_source: str
    file_size: int | None
    #: Byte after the last trace: the file size less any declared data trailer.
    data_end: int | None = None
    trailer_records: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def revision(self) -> tuple[int, int]:
        """The revision to parse by: the structure wins over the declaration."""
        return max(self.declared_revision, self.detected_revision)

    @property
    def revision_label(self) -> str:
        return f"{self.revision[0]}.{self.revision[1]}"

    @property
    def severity(self) -> Severity | None:
        return worst(self.findings)

    def trace_offset(self, index: int) -> int:
        """0-based byte offset of trace `index`.

        Refused only when the stride cannot be computed at all, which means
        variable-length traces. A rev 2 file declaring additional trace headers
        is read under the assumption that every trace carries the declared
        maximum — the standard gives a maximum, not a count — and that
        assumption is already recorded as a finding. Refusing outright would
        make the feature unusable for the files that actually have it.
        """
        if self.trace_bytes is None:
            raise ValueError("trace length is unknown for this file")
        if self.fixed_length is False:
            raise ValueError(
                "this file's traces vary in length, so a trace cannot be found "
                "by multiplying an index; it needs a trace index")
        return self.data_start + index * self.trace_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": {
                "declared": f"{self.declared_revision[0]}.{self.declared_revision[1]}",
                "detected": f"{self.detected_revision[0]}.{self.detected_revision[1]}",
                "used": self.revision_label,
                "signals": [s.to_dict() for s in self.revision_signals],
            },
            "endian": self.endian.name.lower(),
            "endian_source": self.endian_source,
            "data_start": self.data_start,
            "data_start_source": self.data_start_source,
            "samples": {
                "count": self.sample_count,
                "count_source": self.sample_count_source,
                "interval": self.sample_interval,
                "format": self.sample_format,
                "format_name": SAMPLE_FORMAT_NAMES.get(self.sample_format or 0),
                "bytes_per_sample": self.sample_bytes,
            },
            "traces": {
                "count": self.trace_count,
                "count_source": self.trace_count_source,
                "bytes": self.trace_bytes,
                "stride_certain": self.trace_stride_certain,
                "extra_headers": self.extra_trace_headers,
                "fixed_length": self.fixed_length,
            },
            "textual": {
                "primary": self.primary_textual.to_dict(),
                "extended": [h.to_dict() for h in self.extended_textual],
            },
            "binary_header": self.binary.to_dict(),
            "file_size": self.file_size,
            "data_end": self.data_end,
            "trailer_records": self.trailer_records,
            "findings": [f.to_dict() for f in self.findings],
            "severity": self.severity.value if self.severity else None,
        }


# ── byte order ───────────────────────────────────────────────────────────────

def detect_endian(block: bytes) -> tuple[Endian, str, list[Finding]]:
    """Decide byte order from the rev 2 constant, falling back to plausibility.

    `block` is the 400-byte binary header.
    """
    findings: list[Finding] = []
    raw = block[96:100]                      # relative bytes 97-100 → file 3297-3300
    if len(raw) == 4:
        as_big = int.from_bytes(raw, "big", signed=False)
        if as_big == BYTE_ORDER_CONSTANT:
            return Endian.BIG, "rev2_constant", findings
        if as_big == BYTE_ORDER_REVERSED:
            return Endian.LITTLE, "rev2_constant", findings
        if as_big == BYTE_ORDER_PAIRWISE:
            findings.append(error(
                "endian.pairwise_swap",
                "Bytes 3297-3300 indicate a pairwise-swapped byte order, which "
                "OpenSEGY does not decode.",
                byte_range=(3297, 3300)))
            return Endian.BIG, "rev2_constant_pairwise", findings
        if as_big != 0:
            findings.append(warning(
                "endian.constant_unrecognised",
                f"Bytes 3297-3300 hold 0x{as_big:08x}, which is not one of the "
                "byte-order constants rev 2 defines.",
                byte_range=(3297, 3300), evidence={"raw": raw.hex(" ")}))

    big_ok = _header_is_plausible(block, Endian.BIG)
    little_ok = _header_is_plausible(block, Endian.LITTLE)
    if big_ok and not little_ok:
        return Endian.BIG, "plausibility", findings
    if little_ok and not big_ok:
        findings.append(info(
            "endian.little_by_plausibility",
            "No byte-order constant is present and the header only reads as "
            "sense little-endian.",
            byte_range=(3217, 3226)))
        return Endian.LITTLE, "plausibility", findings
    if not big_ok and not little_ok:
        findings.append(warning(
            "endian.undetermined",
            "The binary header does not read as sense in either byte order; "
            "assuming big-endian, as the standard requires.",
            byte_range=(3217, 3226)))
    return Endian.BIG, "default", findings


def _header_is_plausible(block: bytes, endian: Endian) -> bool:
    fmt = decode_scalar(block[24:26], "int16", endian)
    ns = decode_scalar(block[20:22], "int16", endian)
    if fmt not in SAMPLE_BYTES:
        return False
    if ns is None:
        return False
    ns = ns if ns > 0 else ns + 65536
    return _PLAUSIBLE_SAMPLES[0] <= ns <= _PLAUSIBLE_SAMPLES[1]


# ── revision ─────────────────────────────────────────────────────────────────

def read_declared_revision(block: bytes) -> tuple[tuple[int, int], list[Finding]]:
    """Bytes 3501-3502, read as major and minor.

    Rev 1 wrote one int16 whose value is 0x0100, which is byte 3501 = 1 and byte
    3502 = 0 — the same layout rev 2 later made explicit. That is why one read
    serves every revision, and why a file holding 0x0001 here is not revision
    0.1 but a rev-1 file whose writer swapped the two bytes.
    """
    findings: list[Finding] = []
    if len(block) < 302:
        return (0, 0), [warning("revision.header_truncated",
                                "The binary header is too short to hold a revision.")]
    major, minor = block[300], block[301]

    if (major, minor) == (0, 1):
        findings.append(warning(
            "revision.byte_swapped",
            "Bytes 3501-3502 declare revision 0.1, which no SEG-Y revision "
            "defines; this is a rev 1 file whose writer swapped the two bytes.",
            byte_range=(3501, 3502), evidence={"raw": block[300:302].hex(" ")}))
        return (1, 0), findings

    if major > 2:
        findings.append(warning(
            "revision.unknown",
            f"Bytes 3501-3502 declare revision {major}.{minor}, which is newer "
            "than any revision OpenSEGY knows.",
            byte_range=(3501, 3502)))
    elif major == 2 and minor > 1:
        findings.append(info(
            "revision.newer_minor",
            f"Revision 2.{minor} declared; parsed with the rev 2.1 table.",
            byte_range=(3501, 3502)))
    return (major, minor), findings


def detect_revision(block: bytes, endian: Endian,
                    file_size: int | None) -> list[RevisionSignal]:
    """Structural evidence for the revision, independent of what is declared.

    The block is parsed with the widest table first, because a field can only be
    used as evidence once it has been read, and the rev 2.1 table is a superset
    everywhere except bytes 3507-3510 — which is exactly why anything read there
    is treated as weak.
    """
    view = bh.parse(block, major=2, minor=1, endian=endian)
    signals: list[RevisionSignal] = []

    raw_order = block[96:100]
    if len(raw_order) == 4 and int.from_bytes(raw_order, "big") in (
            BYTE_ORDER_CONSTANT, BYTE_ORDER_REVERSED, BYTE_ORDER_PAIRWISE):
        signals.append(RevisionSignal(
            "byte_order_constant", (2, 0), "strong",
            "Bytes 3297-3300 carry the rev 2 byte-order constant.", (3297, 3300)))

    fmt = view.get("sample_format")
    if fmt and SAMPLE_FORMAT_SINCE.get(fmt, (0, 0)) >= (2, 0):
        signals.append(RevisionSignal(
            "rev2_sample_format", (2, 0), "strong",
            f"Sample format {fmt} ({SAMPLE_FORMAT_NAMES.get(fmt)}) was introduced "
            "in rev 2.", (3225, 3226)))

    count = view.get("trace_count")
    if count:
        plausible = file_size is None or 0 < count <= file_size
        signals.append(RevisionSignal(
            "trace_count_field", (2, 0), "strong" if plausible else "weak",
            f"Bytes 3513-3520 declare {count} traces, a rev 2 field.", (3513, 3520)))

    offset = view.get("first_trace_offset")
    if offset:
        plausible = offset >= bh.BASE_DATA_START and (
            file_size is None or offset < file_size)
        signals.append(RevisionSignal(
            "first_trace_offset_field", (2, 0),
            "strong" if plausible else "weak",
            f"Bytes 3521-3528 declare the first trace at byte {offset}, a rev 2 "
            "field.", (3521, 3528)))

    for name, rng in (("ext_samples_per_trace", (3269, 3272)),
                      ("ext_sample_interval", (3273, 3280)),
                      ("ext_ensemble_fold", (3293, 3296))):
        if view.get(name):
            signals.append(RevisionSignal(
                name, (2, 0), "moderate",
                f"The rev 2 field {name} is set; in rev 0 and 1 these bytes are "
                "unassigned and could hold vendor data.", rng))

    # 3507-3510 is one int32 in rev 2.0 and two int16s in rev 2.1. A value that
    # only makes sense read one way is the sole in-file evidence separating the
    # two minor revisions, and it is never better than moderate.
    raw_307 = block[306:310]
    if len(raw_307) == 4 and raw_307 != b"\x00\x00\x00\x00":
        as_i32 = decode_scalar(raw_307, "int32", endian)
        as_i16 = decode_scalar(raw_307[:2], "int16", endian)
        survey = decode_scalar(raw_307[2:], "int16", endian)
        if as_i32 is not None and as_i32 > 65535 and survey in (1, 2, 3, 4):
            signals.append(RevisionSignal(
                "survey_type_field", (2, 1), "moderate",
                f"Bytes 3507-3510 read as one rev 2.0 integer give {as_i32}, "
                f"which is absurd for a trace-header count; read as rev 2.1 they "
                f"give {as_i16} extra trace headers and survey type {survey}.",
                (3507, 3510)))
        else:
            signals.append(RevisionSignal(
                "max_extra_trace_headers", (2, 0), "moderate",
                "Bytes 3507-3510 declare additional trace headers, a rev 2 field.",
                (3507, 3510)))

    if view.get("extended_textual_headers"):
        signals.append(RevisionSignal(
            "extended_textual_headers", (1, 0), "moderate",
            "Bytes 3505-3506 declare extended textual headers, defined in rev 1.",
            (3505, 3506)))
    if view.get("fixed_length_trace_flag"):
        signals.append(RevisionSignal(
            "fixed_length_trace_flag", (1, 0), "weak",
            "Bytes 3503-3504 carry the rev 1 fixed-length trace flag.",
            (3503, 3504)))

    return signals


def _revision_from_signals(signals: list[RevisionSignal]) -> tuple[int, int]:
    for level in ("strong", "moderate"):
        implied = [s.implies for s in signals if s.strength == level]
        if implied:
            best = max(implied)
            # A strong rev 2 signal plus a moderate 2.1 one is a 2.1 file.
            refine = [s.implies for s in signals
                      if s.strength in ("strong", "moderate") and s.implies > best]
            return max(refine) if refine else best
    return (0, 0)


# ── the whole thing ──────────────────────────────────────────────────────────

def scan(obj, *, max_extended_scan: int = 1024) -> SegyStructure:
    """Read every structural header of a SEG-Y and work out its layout.

    Accepts a path, raw bytes, or any object with `read(offset, length)` and
    `.size`. Reads at most 3600 bytes plus the extended textual headers; no
    trace data is touched.
    """
    source = as_source(obj)
    size = source.size
    findings: list[Finding] = []

    primary = textual.read_primary(source)
    findings.extend(textual.check_primary(primary))

    block = source.read(textual.TEXTUAL_HEADER_SIZE, bh.BINARY_HEADER_SIZE)
    if len(block) < bh.BINARY_HEADER_SIZE:
        findings.append(error(
            "structure.binary_header_missing",
            f"The file holds {len(block)} of the 400 bytes the binary header "
            "needs; it is too short to be a SEG-Y.",
            byte_range=(3201, 3600)))

    endian, endian_source, endian_findings = detect_endian(block)
    findings.extend(endian_findings)

    declared, rev_findings = read_declared_revision(block)
    findings.extend(rev_findings)
    signals = detect_revision(block, endian, size)
    detected = _revision_from_signals(signals)
    used = max(declared, detected)

    if detected > declared:
        strong = [s for s in signals if s.strength == "strong"
                  and s.implies > declared]
        findings.append(Finding(
            Severity.WARNING if strong else Severity.INFO,
            "revision.declared_below_structure",
            f"The file declares revision {declared[0]}.{declared[1]} but carries "
            f"revision {detected[0]}.{detected[1]} structures; parsed as "
            f"{used[0]}.{used[1]}.",
            byte_range=(3501, 3502),
            evidence={"declared": f"{declared[0]}.{declared[1]}",
                      "detected": f"{detected[0]}.{detected[1]}",
                      "signals": [s.to_dict() for s in signals]}))

    view = bh.parse(block, major=used[0], minor=used[1], endian=endian)
    findings.extend(bh.check(view))

    # ── where the traces begin ───────────────────────────────────────────────
    declared_ext = view.get("extended_textual_headers")
    extended, ext_findings = textual.read_extended(
        source, declared=declared_ext,
        start_offset=bh.BASE_DATA_START, file_size=size,
        max_scan=max_extended_scan)
    findings.extend(ext_findings)

    computed_start = bh.BASE_DATA_START + len(extended) * textual.TEXTUAL_HEADER_SIZE
    declared_start = view.get("first_trace_offset") or 0

    ns, ns_source = bh.effective_sample_count(view)
    dt, _ = bh.effective_sample_interval(view)
    fmt = view.get("sample_format")
    sample_bytes = SAMPLE_BYTES.get(fmt) if fmt else None

    extra_headers = int(view.get("max_extra_trace_headers") or 0)
    if extra_headers < 0:
        extra_headers = 0
    trace_bytes = None
    if ns and sample_bytes:
        trace_bytes = 240 * (1 + extra_headers) + ns * sample_bytes

    fixed_flag = view.get("fixed_length_trace_flag")
    fixed_length = None if fixed_flag is None else bool(fixed_flag == 1)

    # A file that carries extended textual headers without declaring them has
    # every trace read at the wrong offset, with nothing anywhere to say so.
    # Rescued only when the arithmetic proves it: the corrected offset divides
    # the file into whole traces and the offset the header implies does not.
    if not extended and trace_bytes and size:
        sniffed = textual.sniff_undeclared(
            source, start_offset=bh.BASE_DATA_START, file_size=size)
        if sniffed:
            rescued = bh.BASE_DATA_START + len(sniffed) * textual.TEXTUAL_HEADER_SIZE
            if _divides(size, rescued, trace_bytes) and not _divides(
                    size, computed_start, trace_bytes):
                findings.append(warning(
                    "structure.undeclared_extended_textual_headers",
                    f"The binary header declares no extended textual headers, but "
                    f"{len(sniffed)} record(s) of text follow it, and the file only "
                    f"divides into whole traces from byte {rescued}; the traces are "
                    "read from there.",
                    byte_range=(3505, 3506),
                    evidence={"found": len(sniffed),
                              "declared": declared_ext or 0,
                              "rescued_offset": rescued}))
                extended = sniffed
                computed_start = rescued

    data_start, data_start_source = _settle_data_start(
        computed_start, declared_start, trace_bytes, size, findings)

    stride_certain = True
    if extra_headers:
        findings.append(info(
            "structure.extra_trace_headers_assumed_uniform",
            f"Every trace is assumed to carry the declared maximum of "
            f"{extra_headers} additional trace header(s); the standard gives a "
            "maximum, not a count, so a file that varies needs a trace index.",
            byte_range=(3507, 3508)))
        stride_certain = False
    if fixed_length is False:
        findings.append(warning(
            "structure.variable_trace_length",
            "The fixed-length trace flag is not set, so traces may differ in "
            "length and cannot be addressed by multiplying an index.",
            byte_range=(3503, 3504)))
        stride_certain = False

    data_end, trailer_records = _settle_data_end(view, size, findings)

    trace_count, count_source = _settle_trace_count(
        view, data_end, data_start, trace_bytes, stride_certain, findings)

    return SegyStructure(
        declared_revision=declared,
        detected_revision=detected,
        revision_signals=signals,
        endian=endian,
        endian_source=endian_source,
        binary=view,
        primary_textual=primary,
        extended_textual=extended,
        data_start=data_start,
        data_start_source=data_start_source,
        sample_count=ns,
        sample_count_source=ns_source,
        sample_interval=dt,
        sample_format=fmt,
        sample_bytes=sample_bytes,
        extra_trace_headers=extra_headers,
        trace_bytes=trace_bytes,
        trace_stride_certain=stride_certain,
        fixed_length=fixed_length,
        trace_count=trace_count,
        trace_count_source=count_source,
        file_size=size,
        data_end=data_end,
        trailer_records=trailer_records,
        findings=findings,
    )


def _settle_data_end(view: HeaderView, size: int | None,
                     findings: list[Finding]) -> tuple[int | None, int]:
    """Where the traces stop, which is not always where the file stops.

    Rev 2 allows a data trailer of 3200-byte records after the last trace, and
    declares how many at bytes 3529-3532. Counting those records as traces is
    how a correct file acquires a spurious "trailing bytes" warning and a trace
    count seven too high.
    """
    declared = view.get("data_trailer_stanzas") or 0
    if not declared or size is None:
        return size, 0
    if declared == -1:
        findings.append(info(
            "structure.variable_data_trailer",
            "The file declares a variable-length data trailer; its extent is not "
            "yet computed, so the trace count may include it.",
            byte_range=(3529, 3532)))
        return size, 0
    trailer_bytes = declared * textual.TEXTUAL_HEADER_SIZE
    if trailer_bytes >= size:
        findings.append(warning(
            "structure.data_trailer_implausible",
            f"Bytes 3529-3532 declare {declared} data trailer record(s), which is "
            "more than the file holds.",
            byte_range=(3529, 3532), evidence={"declared": declared}))
        return size, 0
    findings.append(info(
        "structure.data_trailer",
        f"The file declares {declared} data trailer record(s) after the last trace.",
        byte_range=(3529, 3532), evidence={"records": declared}))
    return size - trailer_bytes, declared


def _divides(size: int | None, start: int, trace_bytes: int | None) -> bool:
    """Does the remaining file split into whole traces from `start`?"""
    if not size or not trace_bytes or start >= size:
        return False
    return (size - start) % trace_bytes == 0


def _settle_data_start(computed: int, declared: int, trace_bytes: int | None,
                       size: int | None, findings: list[Finding]) -> tuple[int, str]:
    """Reconcile the counted extended headers with the rev 2 declared offset.

    Neither is trusted blindly. When they disagree, the tie-breaker is the one
    question the file can answer for itself: from which offset does the rest of
    the file divide into whole traces?
    """
    if not declared:
        return computed, "counted_extended_textual_headers"
    if declared == computed:
        return computed, "declared_and_counted_agree"

    computed_fits = _divides(size, computed, trace_bytes)
    declared_fits = _divides(size, declared, trace_bytes)

    if declared_fits and not computed_fits:
        findings.append(warning(
            "structure.data_start_disagrees",
            f"Bytes 3521-3528 put the first trace at {declared} while the "
            f"extended textual headers end at {computed}; the declared offset is "
            "used because only it divides the file into whole traces.",
            byte_range=(3521, 3528),
            evidence={"declared": declared, "counted": computed}))
        return declared, "declared_first_trace_offset"

    if computed_fits and not declared_fits:
        findings.append(warning(
            "structure.data_start_disagrees",
            f"Bytes 3521-3528 put the first trace at {declared} but the file only "
            f"divides into whole traces from {computed}, where the extended "
            "textual headers end; the counted offset is used.",
            byte_range=(3521, 3528),
            evidence={"declared": declared, "counted": computed}))
        return computed, "counted_extended_textual_headers"

    findings.append(warning(
        "structure.data_start_ambiguous",
        f"Bytes 3521-3528 put the first trace at {declared} while the extended "
        f"textual headers end at {computed}, and the file size does not settle "
        "it; the declared offset is used.",
        byte_range=(3521, 3528),
        evidence={"declared": declared, "counted": computed}))
    return declared, "declared_first_trace_offset"


def _settle_trace_count(view: HeaderView, data_end: int | None, data_start: int,
                        trace_bytes: int | None, stride_certain: bool,
                        findings: list[Finding]) -> tuple[int | None, str]:
    declared = view.get("trace_count") or 0
    computed = None
    if data_end and trace_bytes and stride_certain and data_end > data_start:
        computed = (data_end - data_start) // trace_bytes
        remainder = (data_end - data_start) % trace_bytes
        if remainder:
            findings.append(warning(
                "structure.trailing_bytes",
                f"{remainder} byte(s) remain after the last whole trace. This is "
                "a data trailer, a truncated file, or a misread trace length.",
                evidence={"remainder": remainder, "trace_bytes": trace_bytes}))

    if declared and computed is not None and declared != computed:
        findings.append(warning(
            "structure.trace_count_disagrees",
            f"Bytes 3513-3520 declare {declared} traces; the file size gives "
            f"{computed}.",
            byte_range=(3513, 3520),
            evidence={"declared": declared, "computed": computed}))
    if declared:
        return int(declared), "declared"
    if computed is not None:
        return int(computed), "file_size"
    return None, ""
