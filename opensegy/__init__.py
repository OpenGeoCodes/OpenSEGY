"""OpenSEGY — a modern open-source toolkit for SEG-Y.

The library reads a SEG-Y and tells you what is in it, where, and how sure it
is. Its organising idea is a distinction the format itself blurs:

    a *reading* is a fact about bytes — this range, this type, this raw value;
    a *claim* is a belief about the world — this is EPSG:31984.

OpenSEGY produces readings, and never claims. It will tell you that an extended
textual header declares a coordinate system as the text "SIRGAS 2000 / UTM 24S";
it will not tell you which EPSG code that is, because deciding that needs
evidence from outside the file. Keeping the line there is what lets the same
parser serve an inspector, a converter and somebody else's notebook.

Quick start::

    import opensegy

    with opensegy.open("survey.sgy") as segy:
        print(segy.structure.revision_label, segy.n_traces)
        samples = segy.trace(0)                       # float32, whatever the format
        geometry = segy.header_table(["inline", "crossline", "cdp_x", "cdp_y"])
        for finding in segy.findings:
            print(finding.severity.value, finding.message)

`opensegy.scan` does the same without opening the traces, reading at most a few
kilobytes, so it costs the same on a 40 KB line and a 40 GB volume.
"""
from __future__ import annotations

from .binary_header import (
    BASE_DATA_START,
    BINARY_HEADER_SIZE,
    BINARY_HEADER_START,
    TEXTUAL_HEADER_SIZE,
)
from .fields import FieldDef, HeaderView, Reading
from .findings import Finding, Severity, error, info, warning, worst
from .source import ByteSource, FileSource, MemorySource, as_source
from .structure import RevisionSignal, SegyStructure, scan
from .traces import SegyFile, decode_samples, open
from .synthetic import SegyBuilder, Trace, default_textual
from .textual import TextualHeader
from .trace_header import TRACE_HEADER_SIZE, apply_coordinate_scalar
from .types import (
    SAMPLE_BYTES,
    SAMPLE_FORMAT_NAMES,
    Endian,
    SampleFormat,
    decode_scalar,
    encode_scalar,
    ibm32_to_float,
)

from . import binary_header, findings, fixtures, source, structure, synthetic
from . import textual, trace_header, traces, types

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # entry points
    "open", "SegyFile", "scan", "SegyStructure", "RevisionSignal",
    "decode_samples",
    "SegyBuilder", "Trace", "default_textual",
    # readings
    "FieldDef", "Reading", "HeaderView",
    "Finding", "Severity", "error", "warning", "info", "worst",
    "TextualHeader",
    # byte sources
    "ByteSource", "FileSource", "MemorySource", "as_source",
    # primitives
    "Endian", "SampleFormat", "SAMPLE_BYTES", "SAMPLE_FORMAT_NAMES",
    "decode_scalar", "encode_scalar", "ibm32_to_float",
    "apply_coordinate_scalar",
    # constants
    "TEXTUAL_HEADER_SIZE", "BINARY_HEADER_SIZE", "BINARY_HEADER_START",
    "BASE_DATA_START", "TRACE_HEADER_SIZE",
    # modules
    "binary_header", "trace_header", "traces", "textual", "structure",
    "synthetic", "fixtures", "findings", "source", "types",
]
