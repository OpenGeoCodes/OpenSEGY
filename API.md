# OpenSEGY API

Everything below is reachable from the top-level `opensegy` package. Byte
positions are **1-based and inclusive**, the way the SEG-Y specification writes
them; byte *offsets* into the file, where they appear, are 0-based, the way
`seek` takes them. The two are named apart everywhere: `byte_range` is the
former, `offset` and `data_start` the latter.

- [Opening a file](#opening-a-file)
- [Structure](#structure)
- [Headers](#headers)
- [Trace data](#trace-data)
- [Findings](#findings)
- [Byte sources](#byte-sources)
- [Building files](#building-files)
- [Primitives](#primitives)
- [Command line](#command-line)

---

## Opening a file

```python
opensegy.scan(obj, *, max_extended_scan=1024) -> SegyStructure
opensegy.open(obj, **kw) -> SegyFile
```

`obj` is a path, a `bytes`, or any object with `read(offset, length)` and
`.size`. `scan` answers the structural questions and reads only the textual
header, the binary header and any extended textual headers — a few kilobytes,
whatever the file's size. `open` does the same and keeps the source ready for
trace access.

`max_extended_scan` caps the walk when a file declares a *variable* number of
extended textual headers (byte 3505 holds -1) and never writes the end-text
stanza that should terminate it. Hitting the cap is a finding, not an exception.

`SegyFile` is a context manager and closes its source on exit.

```python
with opensegy.open("survey.sgy") as segy:
    ...
```

---

## Structure

`SegyStructure` is what `scan` returns and what `SegyFile.structure` holds.

### Revision

| Attribute | Meaning |
|---|---|
| `declared_revision` | `(major, minor)` read from bytes 3501-3502 |
| `detected_revision` | `(major, minor)` implied by what the file actually contains |
| `revision` | the one used for parsing: the higher of the two |
| `revision_label` | `revision` as `"2.1"` |
| `revision_signals` | `list[RevisionSignal]`, the evidence behind `detected_revision` |

They are kept apart because the declared value has been written wrongly for
twenty years. A `RevisionSignal` carries `name`, `implies`, `strength`
(`"strong" | "moderate" | "weak"`), `detail` and `byte_range`.

### Byte order

| Attribute | Meaning |
|---|---|
| `endian` | `Endian.BIG` or `Endian.LITTLE` |
| `endian_source` | `"rev2_constant"`, `"plausibility"` or `"default"` |

Revision 2 put a known constant at bytes 3297-3300 so this can be read. Older
files have no such constant and the header is tried both ways.

### Where the data is

| Attribute | Meaning |
|---|---|
| `data_start` | 0-based byte offset of the first trace |
| `data_start_source` | how it was settled, e.g. `"counted_extended_textual_headers"` |
| `data_end` | byte after the last trace: the size less any declared data trailer |
| `trailer_records` | number of 3200-byte data trailer records |
| `file_size` | as reported by the source |

`data_start` is **not** 3600 for every file. Extended textual headers have been
legal since revision 1, and a reader that assumes 3600 reads every trace
thousands of bytes out of position with nothing to show for it.

```python
s = opensegy.scan("survey.sgy")
s.data_start, s.data_start_source
# (10000, 'counted_extended_textual_headers')
```

### Traces and samples

| Attribute | Meaning |
|---|---|
| `trace_count` / `trace_count_source` | `"declared"` or `"file_size"`; `None` at variable length |
| `trace_bytes` | header(s) + samples, in bytes |
| `trace_stride_certain` | `False` when uniformity is assumed rather than known |
| `extra_trace_headers` | additional 240-byte headers per trace (revision 2) |
| `fixed_length` | the revision 1 flag, or `None` if unwritten |
| `sample_count` / `sample_count_source` | prefers the 32-bit revision 2 field |
| `sample_interval`, `sample_format`, `sample_bytes` | |

```python
s.trace_offset(index) -> int          # 0-based, raises at variable length
```

### The rest

| Attribute | Meaning |
|---|---|
| `binary` | `HeaderView` over the binary file header |
| `primary_textual` | `TextualHeader` for bytes 1-3200 |
| `extended_textual` | `list[TextualHeader]` |
| `findings` | `list[Finding]` |
| `severity` | the worst severity present, or `None` |
| `to_dict()` | everything above, JSON-safe, raw bytes as hex |

---

## Headers

### `HeaderView`

A parsed block. Subscripting gives the **value**, which is what calling code
usually wants; `.reading()` gives the whole `Reading` when the question is about
provenance.

```python
view = segy.header(0)
view["inline"]                 # 1256
view.get("inline", default=0)
view.reading("inline")         # Reading
view.at(3789)                  # which field covers this absolute byte
view.values()                  # {name: value}
view.to_dict()                 # {name: reading-as-dict}
len(view); list(view)          # iterates Readings
```

### `Reading`

One value and everything needed to argue about it later.

| Field | Meaning |
|---|---|
| `name`, `description` | |
| `start`, `end`, `byte_range` | 1-based inclusive, absolute in the file |
| `dtype` | `"int16"`, `"ieee64"`, `"ibm32"`, `"char8"`, … |
| `raw`, `hex` | the bytes themselves |
| `value` | decoded |
| `interpretation` | a code's meaning, e.g. `"4-byte IEEE float"`; never replaces `value` |
| `source` | `"binary_header"`, `"trace_header"`, `"trace_header_ext_1"`, … |
| `origin` | `"standard"` or `"vendor"` |
| `since` | the revision that first defined the field |
| `truncated` | the field ran past the end of the block |

The raw bytes are kept beside the decoded value deliberately. When a delivery
turns out to carry centimetres where its card promised metres, the bytes are the
only thing that settles it.

### `FieldDef`

Where a field lives, per some standard or declaration: `name`, `start`, `dtype`,
`description`, `since`, `origin`, plus `width`, `end` and
`read(block, *, endian, block_offset, source) -> Reading`.

### Field tables

```python
opensegy.binary_header.fields_for(major, minor=0) -> list[FieldDef]
opensegy.binary_header.unassigned_ranges(major, minor=0)
opensegy.binary_header.parse(block, *, major, minor=0, endian) -> HeaderView
opensegy.binary_header.check(view) -> list[Finding]
opensegy.binary_header.effective_sample_count(view) -> (int | None, str)
opensegy.binary_header.effective_sample_interval(view) -> (float | None, str)

opensegy.trace_header.fields_for(major=2, minor=1, *, extension=False,
                                 only_defined=False) -> list[FieldDef]
opensegy.trace_header.parse(block, *, major, minor, endian, offset,
                            extension=False, source=...) -> HeaderView
opensegy.trace_header.parse_trace(blocks, ...) -> list[HeaderView]
```

The binary-header table is revision-dependent and not only by addition: between
2.0 and 2.1 the field at byte 3507 narrowed from int32 to int16 and bytes
3509-3510 became the survey type. So the revision has to be settled before the
table is chosen.

The trace-header table is **not** restricted by revision. No trace-header field
changes position or type between revisions, and plenty of deliveries that
declare revision 0 carry an inline at byte 189 anyway. `only_defined=True`
restricts it, which is what a validator wants and a reader does not.

### Textual headers

`TextualHeader` has `index` (0 for the mandatory one), `offset`, `raw`, `text`,
`encoding`, `printable_ratio`, `cards`, `is_extended`, `stanza_label`,
`ends_text` and `to_dict()`.

```python
opensegy.textual.decode(raw) -> (text, encoding, ratio)
opensegy.textual.read_primary(source, *, offset=0) -> TextualHeader
opensegy.textual.read_extended(source, *, declared, start_offset, file_size,
                               max_scan=1024) -> (list, list[Finding])
opensegy.textual.sniff_undeclared(source, *, start_offset, file_size, max_scan=16)
```

`encoding` is chosen by result across cp037, cp500, ASCII and latin-1, not
assumed. `printable_ratio` counts ASCII printable characters with NUL excluded
from the denominator: real headers score 1.00 and trace data in any sample
format scores below 0.40, so a low ratio means the block is not text.

`stanza_label` returns `"SEG: Layout 1.0"` for a record that opens a stanza, of
any namespace. Reading what is *inside* a stanza is not implemented yet.

### Coordinate scalar

```python
opensegy.apply_coordinate_scalar(value, scalar) -> float | None
```

Negative divides, positive multiplies, zero and `None` mean no scaling.

---

## Trace data

```python
segy.n_traces            # raises at variable length
segy.n_samples
segy.trace(index)                       -> np.ndarray, float32
segy.traces(start=0, stop=None)         -> np.ndarray, (n_traces, n_samples)
segy[index]; segy[start:stop]; iter(segy)
segy.header(index)                      -> HeaderView
segy.header_extensions(index)           -> list[HeaderView]
segy.header_block(start=0, stop=None, *, step=1, chunk=4096) -> np.ndarray (n, 240)
segy.header_table(fields=None, *, start=0, stop=None, step=1) -> dict[str, np.ndarray]
```

Samples come back as `float32` whatever the file holds, including IBM
hexadecimal float and the three-byte integers revision 2 added. Integer formats
are widened rather than kept as integers, because a caller who asked for samples
wants amplitudes.

`traces()` reads a range in one request rather than one per trace, which on
object storage is the whole cost.

`header_table` is the one worth knowing about. Building a survey's geometry means
reading 240 bytes per trace and skipping the samples:

```python
with opensegy.open("volume.sgy") as segy:
    g = segy.header_table(["inline", "crossline", "cdp_x", "cdp_y"])
    g["inline"].min(), g["inline"].max()
```

Negative indices work on `trace()`; out of range raises `IndexError`, and a short
read raises `EOFError` rather than returning padded data.

```python
opensegy.decode_samples(raw, sample_format, endian=Endian.BIG) -> np.ndarray
```

Decodes packed sample bytes directly, if you are managing the reads yourself.

---

## Findings

```python
Finding(severity, code, message, byte_range=None, evidence={})
Severity.ERROR | Severity.WARNING | Severity.INFO
opensegy.worst(findings) -> Severity | None
opensegy.error(code, message, **kw); .warning(...); .info(...)
```

`code` is a stable machine key such as `"revision.declared_below_structure"`, so
filtering and suppression have something that will not change casually.
`message` is one sentence written for a geoscientist. `byte_range` points at the
bytes the finding came from.

Severity is three levels on purpose: *would this stop a load?* has to have an
answer.

Findings you will meet often:

| Code | Means |
|---|---|
| `revision.declared_below_structure` | declares rev 1, carries rev 2 structures |
| `revision.byte_swapped` | declares 0.1, which is a rev 1 file written backwards |
| `structure.undeclared_extended_textual_headers` | text records the header never declared |
| `structure.data_start_disagrees` | byte 3521 and the counted headers disagree |
| `structure.trace_count_disagrees` | byte 3513 and the file size disagree |
| `structure.variable_trace_length` | traces cannot be addressed by index |
| `structure.trailing_bytes` | bytes left after the last whole trace |
| `binary_header.sample_count_disagrees` | 16-bit and 32-bit counts differ |
| `textual.not_text` | the first 3200 bytes are not a textual header |

---

## Byte sources

OpenSEGY never opens a URL and imports no storage client. It reads through
whatever object implements:

```python
read(offset, length) -> bytes        # offset is 0-based
size -> int | None
```

Supplied: `FileSource(path)`, `MemorySource(data)`, and `as_source(obj)` which
accepts a path, bytes, or something already conforming. `ByteSource` is the
runtime-checkable protocol. Subclasses of the built-in sources also get
`read_many(ranges)`, which a remote implementation should override to coalesce a
batch into one request.

An adapter is usually four lines:

```python
class S3Source:
    def __init__(self, bucket, key, size): ...
    def read(self, offset, length):
        end = min(offset + length, self.size) - 1
        return s3.get_object(Bucket=..., Key=..., Range=f"bytes={offset}-{end}")["Body"].read()
    @property
    def size(self): return self._size

opensegy.scan(S3Source(...))         # nothing is downloaded
```

---

## Building files

`SegyBuilder` writes SEG-Y through the same field tables the parser reads
through, so a fixture cannot drift from the code that checks it.

```python
from opensegy import SegyBuilder

data = (SegyBuilder(revision=(2, 1), sample_format=5, survey_type=3)
        .add_grid(inlines=range(100, 140), crosslines=range(200, 260))
        .build())
```

| Argument | Default | |
|---|---|---|
| `revision` | `(1, 0)` | the structures actually written |
| `endian` | `Endian.BIG` | |
| `sample_format` | `5` | any code the standard defines |
| `samples_per_trace`, `sample_interval_us` | `51`, `4000` | |
| `textual`, `textual_encoding` | generated, `cp037` | |
| `extended_textual` | `()` | one string per record |
| `extra_trace_headers` | `0` | revision 2 additional headers |
| `fixed_length` | `True` | |
| `survey_type` | `None` | revision 2.1 |
| `data_trailer` | `()` | |
| `measurement_system` | `1` | 1 metres, 2 feet |

Every argument beginning `declared_` writes a value into the header **without
changing what is produced**, which is how a deliberately inconsistent file is
made: `declared_revision`, `declared_extended_count`, `declared_trace_count`,
`declared_first_trace_offset`, `declared_samples_per_trace`,
`write_byte_order_constant`. Defaults are always truthful.

```python
# Declares rev 1, contains rev 2. For testing that a reader notices.
broken = SegyBuilder(revision=(2, 0), declared_revision=(1, 0)).add_trace().build()
```

Methods: `add_trace(headers, samples, extensions)`, `add_grid(...)`, `build()`,
`write(path)`. Writing is strict — a value that does not fit its field raises
`ValueError` naming the value and the field.

`opensegy.default_textual(lines=None)` builds the 40 cards of 80 characters a
textual header is, numbered the way processors number them, for when you want
your own text without counting columns. The builder and the rest of the module
live in `opensegy.synthetic`.

### Fixtures

```python
from opensegy.fixtures import FIXTURES, materialise
FIXTURES["rev21/layout_stanza"]()     # -> bytes
materialise("./segy-fixtures")        # -> list[Path]
```

Nineteen files covering revisions 0 through 2.1, both byte orders, and seven
named defects under `broken/`. Generated rather than checked in: a binary in a
repository is a fact nobody can read in a diff.

---

## Primitives

```python
Endian.BIG | Endian.LITTLE            # .prefix gives ">" or "<"
SampleFormat                           # IntEnum of the format codes
SAMPLE_BYTES: dict[int, int]
SAMPLE_FORMAT_NAMES: dict[int, str]
decode_scalar(raw, dtype, endian=Endian.BIG)
encode_scalar(value, dtype, endian=Endian.BIG) -> bytes
ibm32_to_float(raw, endian=Endian.BIG) -> float
TEXTUAL_HEADER_SIZE = 3200
BINARY_HEADER_SIZE  = 400
BINARY_HEADER_START = 3201
BASE_DATA_START     = 3600
TRACE_HEADER_SIZE   = 240
```

Header dtypes: `int8`, `uint8`, `int16`, `uint16`, `int24`, `uint24`, `int32`,
`uint32`, `int64`, `uint64`, `ieee32`, `ieee64`, `ibm32`, `charN`.

A short or malformed buffer decodes to `None` rather than raising, because a
truncated file must still be describable.

---

## Command line

```
python -m opensegy inspect FILE [--json]
python -m opensegy fixtures DIRECTORY
python -m opensegy --version
```

`inspect` prints the revision, byte order, where the traces start, the counts,
the stanzas and the findings. It exits non-zero when a finding is an error.
`--json` gives the same content as `SegyStructure.to_dict()`.
