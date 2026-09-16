"""The Binary File Header, file bytes 3201-3600.

Field positions below are **relative to the block**, so byte 1 here is file byte
3201, which is how the specification numbers them once you are inside the block
and how `FieldDef` expects them.

The table is revision-dependent, and not only by addition. Between Rev 2.0 and
Rev 2.1 the maximum-additional-trace-headers field at relative byte 307 narrowed
from int32 to int16, and the freed bytes 309-310 became the survey type. So

    you cannot parse byte 3507 onwards without first deciding which revision
    you are in,

which is the concrete reason `structure.py` resolves the revision before this
module is asked for a table, and the reason a file whose declared revision is
wrong produces garbage in exactly that range.

Offsets were taken from the SEG-Y specifications and cross-checked against the
Apache-2.0 `segy` package from TGS and against Equinor's `segyio`. Byte
positions are facts about the standard, not anybody's code.
"""
from __future__ import annotations

from .fields import FieldDef, HeaderView, Reading
from .findings import Finding, info, warning
from .types import (
    SAMPLE_BYTES,
    SAMPLE_FORMAT_NAMES,
    SAMPLE_FORMAT_SINCE,
    Endian,
)

#: File byte at which the binary header starts, 1-based.
BINARY_HEADER_START = 3201
BINARY_HEADER_SIZE = 400
TEXTUAL_HEADER_SIZE = 3200
#: Where trace data begins when there are no extended textual headers.
BASE_DATA_START = TEXTUAL_HEADER_SIZE + BINARY_HEADER_SIZE   # 3600


# ── Rev 0: the original block ────────────────────────────────────────────────
_REV0: tuple[FieldDef, ...] = (
    FieldDef("job_id",                     1, "int32",  "Job identification number"),
    FieldDef("line_number",                5, "int32",  "Line number"),
    FieldDef("reel_number",                9, "int32",  "Reel number"),
    FieldDef("traces_per_ensemble",       13, "int16",  "Data traces per ensemble"),
    FieldDef("aux_traces_per_ensemble",   15, "int16",  "Auxiliary traces per ensemble"),
    FieldDef("sample_interval",           17, "int16",  "Sample interval (us, or Hz/m for other domains)"),
    FieldDef("sample_interval_orig",      19, "int16",  "Sample interval of original field recording"),
    FieldDef("samples_per_trace",         21, "int16",  "Samples per data trace"),
    FieldDef("samples_per_trace_orig",    23, "int16",  "Samples per data trace, original field recording"),
    FieldDef("sample_format",             25, "int16",  "Data sample format code"),
    FieldDef("ensemble_fold",             27, "int16",  "Ensemble fold"),
    FieldDef("trace_sorting",             29, "int16",  "Trace sorting code"),
    FieldDef("vertical_sum",              31, "int16",  "Vertical sum code"),
    FieldDef("sweep_frequency_start",     33, "int16",  "Sweep frequency at start (Hz)"),
    FieldDef("sweep_frequency_end",       35, "int16",  "Sweep frequency at end (Hz)"),
    FieldDef("sweep_length",              37, "int16",  "Sweep length (ms)"),
    FieldDef("sweep_type",                39, "int16",  "Sweep type code"),
    FieldDef("sweep_channel",             41, "int16",  "Trace number of sweep channel"),
    FieldDef("sweep_taper_start",         43, "int16",  "Sweep trace taper length at start (ms)"),
    FieldDef("sweep_taper_end",           45, "int16",  "Sweep trace taper length at end (ms)"),
    FieldDef("taper_type",                47, "int16",  "Taper type"),
    FieldDef("correlated_traces",         49, "int16",  "Correlated data traces"),
    FieldDef("binary_gain_recovered",     51, "int16",  "Binary gain recovered"),
    FieldDef("amplitude_recovery",        53, "int16",  "Amplitude recovery method"),
    FieldDef("measurement_system",        55, "int16",  "Measurement system (1 = metres, 2 = feet)"),
    FieldDef("impulse_polarity",          57, "int16",  "Impulse signal polarity"),
    FieldDef("vibratory_polarity",        59, "int16",  "Vibratory polarity code"),
)

# ── Rev 1: the revision block at 3501 ────────────────────────────────────────
# Rev 1 wrote a single int16 here, where 0x0100 means "1.0". Rev 2 redefined the
# same two bytes as a pair of unsigned bytes, major then minor, which reads the
# same for a correct rev-1 file. `structure.py` exploits that to read one shape
# for every revision, and to catch the vendors who wrote 0x0001 instead.
_REV1: tuple[FieldDef, ...] = (
    FieldDef("fixed_length_trace_flag",  303, "int16",
             "Fixed length trace flag (1 = every trace has the same length)", since=(1, 0)),
    FieldDef("extended_textual_headers", 305, "int16",
             "Number of 3200-byte extended textual headers (-1 = variable)", since=(1, 0)),
)

# ── Rev 2: the extended counters, and the byte-order constant ────────────────
_REV2_EXTENSIONS: tuple[FieldDef, ...] = (
    FieldDef("ext_traces_per_ensemble",       61, "int32",
             "Extended data traces per ensemble", since=(2, 0)),
    FieldDef("ext_aux_traces_per_ensemble",   65, "int32",
             "Extended auxiliary traces per ensemble", since=(2, 0)),
    FieldDef("ext_samples_per_trace",         69, "int32",
             "Extended samples per data trace", since=(2, 0)),
    FieldDef("ext_sample_interval",           73, "ieee64",
             "Extended sample interval", since=(2, 0)),
    FieldDef("ext_sample_interval_orig",      81, "ieee64",
             "Extended sample interval, original field recording", since=(2, 0)),
    FieldDef("ext_samples_per_trace_orig",    89, "int32",
             "Extended samples per trace, original field recording", since=(2, 0)),
    FieldDef("ext_ensemble_fold",             93, "int32",
             "Extended ensemble fold", since=(2, 0)),
    FieldDef("byte_order_constant",           97, "int32",
             "Integer constant 0x01020304, for unambiguous byte-order detection",
             since=(2, 0)),
)

_REV2_TAIL: tuple[FieldDef, ...] = (
    FieldDef("time_basis",           311, "int16",  "Time basis code", since=(2, 0)),
    FieldDef("trace_count",          313, "uint64", "Number of traces in this file", since=(2, 0)),
    FieldDef("first_trace_offset",   321, "uint64",
             "Byte offset of the first trace relative to the start of file", since=(2, 0)),
    FieldDef("data_trailer_stanzas", 329, "int32",
             "Number of 3200-byte data trailer stanza records (-1 = variable)", since=(2, 0)),
)

#: Rev 2.0 spelling of the field at relative 307.
_REV20_MAX_EXT_TRACE_HEADERS = FieldDef(
    "max_extra_trace_headers", 307, "int32",
    "Maximum number of additional 240-byte trace headers", since=(2, 0))

#: Rev 2.1 narrowed it and gave 309-310 to the survey type.
_REV21_TAIL: tuple[FieldDef, ...] = (
    FieldDef("max_extra_trace_headers", 307, "int16",
             "Maximum number of additional 240-byte trace headers", since=(2, 1)),
    FieldDef("survey_type", 309, "int16", "Survey type", since=(2, 1)),
)

#: Always present, whatever the revision claims: the two bytes that carry it.
_REVISION_FIELDS: tuple[FieldDef, ...] = (
    FieldDef("revision_major", 301, "uint8", "SEG-Y format revision, major", since=(1, 0)),
    FieldDef("revision_minor", 302, "uint8", "SEG-Y format revision, minor", since=(2, 0)),
)


def fields_for(major: int, minor: int = 0) -> list[FieldDef]:
    """The binary-header field table as it stands in revision `major.minor`.

    Unknown or absurd revisions fall back to the widest table that can be read
    without misinterpreting bytes, which is rev 2.1 minus the parts that moved.
    Being generous here is safe because every field carries its own `since`, so
    a caller can always ask "was this field even defined when this file was
    written?".
    """
    out = list(_REV0)
    out.extend(_REVISION_FIELDS)
    if (major, minor) >= (1, 0):
        out.extend(_REV1)
    if (major, minor) >= (2, 0):
        out.extend(_REV2_EXTENSIONS)
        if (major, minor) >= (2, 1):
            out.extend(_REV21_TAIL)
        else:
            out.append(_REV20_MAX_EXT_TRACE_HEADERS)
        out.extend(_REV2_TAIL)
    out.sort(key=lambda f: f.start)
    return out


#: Byte ranges the standard leaves unassigned, per revision family. Reported so
#: that a file using them for vendor data can be *seen* to be doing so rather
#: than silently ignored.
def unassigned_ranges(major: int, minor: int = 0) -> list[tuple[int, int]]:
    if (major, minor) >= (2, 0):
        return [(101, 300), (333, 400)]
    return [(61, 300), (307, 400)]


_INTERPRETERS: dict[str, dict[int, str]] = {
    "sample_format": SAMPLE_FORMAT_NAMES,
    "measurement_system": {1: "metres", 2: "feet"},
    "fixed_length_trace_flag": {0: "not fixed, or unspecified", 1: "fixed length"},
    "trace_sorting": {
        -1: "other", 0: "unknown", 1: "as recorded", 2: "CDP ensemble",
        3: "single fold continuous profile", 4: "horizontally stacked",
        5: "common source point", 6: "common receiver point",
        7: "common offset point", 8: "common mid-point",
        9: "common conversion point",
    },
    "time_basis": {
        1: "local", 2: "GMT", 3: "other", 4: "UTC", 5: "GPS",
    },
    "survey_type": {
        0: "unspecified", 1: "2D", 2: "2D with depth", 3: "3D", 4: "3D with depth",
    },
}


def _interpret(name: str, value) -> str | None:
    table = _INTERPRETERS.get(name)
    if table is None or value is None:
        return None
    return table.get(value)


def parse(block: bytes, *, major: int, minor: int = 0,
          endian: Endian = Endian.BIG) -> HeaderView:
    """Decode the 400-byte binary header into readings.

    `block` is the raw header, not the whole file. A short block still parses;
    the fields that fall off the end come back truncated.
    """
    readings: list[Reading] = []
    for fd in fields_for(major, minor):
        r = fd.read(block, endian=endian,
                    block_offset=BINARY_HEADER_START, source="binary_header")
        readings.append(r.with_interpretation(_interpret(fd.name, r.value)))
    return HeaderView(readings, block=block,
                      block_offset=BINARY_HEADER_START, endian=endian)


def effective_sample_count(view: HeaderView) -> tuple[int | None, str]:
    """Samples per trace, preferring the Rev 2 extended field when it speaks.

    Rev 2 added a 32-bit count precisely because the 16-bit one overflows past
    65535 samples, which a long record at a fine interval reaches easily. When
    both are set and disagree, the extended one wins and the disagreement is a
    finding, not a silent choice.
    """
    ext = view.get("ext_samples_per_trace")
    base = view.get("samples_per_trace")
    if ext:
        return int(ext), "ext_samples_per_trace"
    if base:
        # The 16-bit field is signed in the standard but never negative in
        # practice; a value above 32767 arrives here as a negative number.
        return (int(base) if base > 0 else int(base) + 65536), "samples_per_trace"
    return None, ""


def effective_sample_interval(view: HeaderView) -> tuple[float | None, str]:
    """Sample interval, preferring the Rev 2 double. Same rule as above."""
    ext = view.get("ext_sample_interval")
    if ext:
        return float(ext), "ext_sample_interval"
    base = view.get("sample_interval")
    if base:
        return float(base if base > 0 else base + 65536), "sample_interval"
    return None, ""


def check(view: HeaderView) -> list[Finding]:
    """Internal consistency of the binary header alone.

    Nothing here compares the header to the trace data or to anything outside
    the file; that belongs to whoever holds both.
    """
    out: list[Finding] = []

    fmt = view.get("sample_format")
    if fmt is None or fmt == 0:
        out.append(warning(
            "binary_header.sample_format_missing",
            "The binary header declares no data sample format.",
            byte_range=(3225, 3226)))
    elif fmt not in SAMPLE_BYTES:
        out.append(warning(
            "binary_header.sample_format_unknown",
            f"Data sample format code {fmt} is not defined by any SEG-Y revision.",
            byte_range=(3225, 3226), evidence={"code": fmt}))
    elif fmt == 4:
        out.append(warning(
            "binary_header.sample_format_withdrawn",
            "Data sample format 4, fixed-point with gain, was withdrawn after rev 1.",
            byte_range=(3225, 3226)))

    ns, ns_src = effective_sample_count(view)
    if not ns:
        out.append(warning(
            "binary_header.sample_count_missing",
            "The binary header declares no sample count.",
            byte_range=(3221, 3222)))
    elif ns_src == "ext_samples_per_trace":
        base = view.get("samples_per_trace") or 0
        if base and base != ns and not (base == -1 or base == 65535):
            out.append(warning(
                "binary_header.sample_count_disagrees",
                f"The 16-bit sample count says {base} and the rev 2 extended "
                f"count says {ns}; the extended field is used.",
                byte_range=(3221, 3222),
                evidence={"samples_per_trace": base, "ext_samples_per_trace": ns}))

    dt, dt_src = effective_sample_interval(view)
    if not dt:
        out.append(warning(
            "binary_header.sample_interval_missing",
            "The binary header declares no sample interval.",
            byte_range=(3217, 3218)))

    if view.get("extended_textual_headers") not in (None, 0):
        n = view.get("extended_textual_headers")
        out.append(info(
            "binary_header.extended_textual_headers",
            ("The file declares a variable number of extended textual headers, "
             "terminated by an end-text stanza."
             if n == -1 else
             f"The file declares {n} extended textual header record(s)."),
            byte_range=(3505, 3506), evidence={"declared": n}))

    if view.get("max_extra_trace_headers"):
        out.append(info(
            "binary_header.trace_header_extensions",
            f"The file declares up to {view['max_extra_trace_headers']} additional "
            "240-byte trace header(s) per trace.",
            byte_range=(3507, 3508)))

    fmt_since = SAMPLE_FORMAT_SINCE.get(fmt or 0, (0, 0))
    if fmt_since >= (2, 0):
        out.append(info(
            "binary_header.rev2_sample_format",
            f"Sample format {fmt} ({SAMPLE_FORMAT_NAMES.get(fmt, '?')}) was "
            "introduced in rev 2.",
            byte_range=(3225, 3226)))

    return out
