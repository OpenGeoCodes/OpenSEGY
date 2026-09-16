# OpenSEGY

**Modern open-source toolkit for SEG-Y.**

SEG-Y is a container. What it contains is a survey's geometry, its coordinate
system, its processing history and whatever else the people who wrote it chose
to put there. OpenSEGY is the layer that turns that into information you can
read, check and act on.

```bash
pip install opensegy
```

```python
import opensegy

with opensegy.open("survey.sgy") as segy:
    print(segy.structure.revision_label)   # 2.1
    print(segy.structure.data_start)       # 10000, not the 3600 everyone assumes
    print(segy.n_traces)                   # 2184320

    samples = segy.trace(0)                # float32, whatever the format on disk
    gather = segy[100:140]                 # (40, n_samples)

    # The geometry of the whole survey, without reading a single sample.
    g = segy.header_table(["inline", "crossline", "cdp_x", "cdp_y"])

    for finding in segy.findings:
        print(finding.severity.value, finding.message)
```

`opensegy.scan` answers the structural questions without opening the traces,
reading a few kilobytes, so it costs the same on a 40 KB line as on a 40 GB
volume. Give either function a path, a `bytes`, or any object with
`read(offset, length)` and `.size` — an fsspec file, an S3 range reader, your own
cache. OpenSEGY never opens a URL itself, and numpy is its only dependency.

## Why another SEG-Y library

Because of a bug that costs real money and makes no noise.

The standard has allowed extended textual headers since revision 1, in 2002.
Most readers seek to byte 3600 and start reading traces. A file with two
extended textual headers then has **every trace read 6400 bytes out of
position**, and nothing anywhere reports an error. You get a volume, it looks
plausible, and it is wrong.

OpenSEGY computes where the data starts, and says how it knows:

```python
>>> segy.data_start, segy.data_start_source
(10000, 'counted_extended_textual_headers')
```

When the file declares one thing and contains another, it says that too, rather
than choosing in silence:

```
WARNING  The file declares revision 1.0 but carries revision 2.0 structures;
         parsed as 2.0.
WARNING  Bytes 3521-3528 put the first trace at 3600 but the file only divides
         into whole traces from 6800, where the extended textual headers end;
         the counted offset is used.
WARNING  Bytes 3501-3502 declare revision 0.1, which no SEG-Y revision defines;
         this is a rev 1 file whose writer swapped the two bytes.
```

## Readings, not claims

Every value carries where it came from.

```python
>>> r = segy.binary.reading("sample_format")
>>> r.byte_range, r.hex, r.value, r.interpretation
((3225, 3226), '00 05', 5, '4-byte IEEE float')
```

The distinction the library is built on:

> a **reading** is a fact about bytes — this range, this type, this raw value;
> a **claim** is a belief about the world — this file is in EPSG:31984.

OpenSEGY produces readings and never claims. It will tell you that an extended
textual header declares a coordinate system as the text `SIRGAS 2000 / UTM 24S`.
It will not tell you which EPSG code that is, because deciding needs evidence
from outside the file. Guessing on your behalf, and then forgetting that it
guessed, is how a volume ends up in the wrong hemisphere.

The raw bytes are always kept beside the decoded value. When a delivery turns
out to carry centimetres where its header promised metres, the bytes are the
only thing that settles it.

## Revision 2 and 2.1

Revision is read *and* detected, separately, because the declared value has been
written wrongly by vendors for twenty years.

```python
>>> segy.declared_revision, segy.detected_revision
((1, 0), (2, 0))
>>> [s.detail for s in segy.revision_signals]
['Bytes 3297-3300 carry the rev 2 byte-order constant.',
 'Sample format 6 (8-byte IEEE float) was introduced in rev 2.']
```

Revision 2.1 moved a field, and the move is a trap: at byte 3507 revision 2.0
has one 32-bit integer, while 2.1 has a 16-bit integer plus the survey type at
3509. You cannot parse byte 3507 without first deciding which revision you are
in. OpenSEGY resolves the revision first, then picks the table.

Byte order is read from the constant revision 2 put at bytes 3297-3300, and
falls back to plausibility for older files. Little-endian files work.

## Building test files

Real deliveries arrive in whatever shape their vendor wrote. They cannot be
asked for a file with two extended textual headers, a variable trace length and
a declared revision that contradicts its own structure. So OpenSEGY builds them,
using the same field tables it reads through.

```python
from opensegy import SegyBuilder

data = (SegyBuilder(revision=(2, 1), sample_format=5, survey_type=3)
        .add_grid(inlines=range(100, 140), crosslines=range(200, 260))
        .build())

# Declare one thing, contain another — for testing that a reader notices.
broken = SegyBuilder(revision=(2, 0), declared_revision=(1, 0)).build()
```

## Reading data

Samples come back as `float32` whatever the file holds, including IBM
hexadecimal float and the three-byte integers revision 2 added. Decoding is
vectorised: about 950 MB/s for IBM float on one core, exact against the scalar
decoder, and a byteswap at several GB/s for IEEE float. The top byte of an IBM
word is the sign plus the exponent, so 256 values cover every scale factor and
the conversion is a lookup and a multiply rather than five passes of arithmetic.

`header_table` is the one worth knowing about. Building a survey's geometry means
reading 240 bytes per trace and skipping the samples, which on a 40 GB volume is
a few hundred megabytes rather than 40 GB. Traces are read in runs so a remote
source sees a manageable number of requests.

Verified against 21 real SEG-Y deliveries from Brazil's national agency,
revisions 0 and 1: every sample and every trace header is **bit-for-bit
identical** to what segyio reads.

## Scope today

Version 0.1 covers the structure, the headers and the data:

- declared and detected revision, 0 through 2.1, with the evidence for each
- the complete binary file header, per revision, as byte-ranged readings
- byte order from the revision 2 constant, or by plausibility
- textual headers, EBCDIC and ASCII, encoding chosen by result
- extended textual headers, including variable-length runs and undeclared ones
- the standard 240-byte trace header, plus the architecture for revision 2's
  additional headers
- every sample format code, 1 through 16, including IBM float
- trace samples as float32 arrays, one trace, a slice, or all of them
- every trace header as columns, without touching a sample
- a synthetic file builder, correct files and deliberately broken ones

Not yet: parsing the content of stanzas such as `SEG:Layout` and
`SEG:Processing History`, embedded objects, the content of the data trailer, and
writing. They are next, in that order.

No other open library parses `SEG:Layout`, trace header extensions or embedded
objects today, which is why this one exists.

## Documentation

- [`API.md`](API.md) — the full public surface, organised by task
- [`CHANGELOG.md`](CHANGELOG.md)
- [`examples/`](examples/) — inspect a file, read a survey's geometry, read
  straight from object storage without downloading

Every module carries a docstring explaining not just what it does but why it does
it that way, including the measurements behind the choices. `help(opensegy)` and
`help(opensegy.structure)` are worth a minute.

## License and attribution

Apache-2.0.

Byte positions were taken from the SEG-Y specifications and cross-checked
against the Apache-2.0 [`segy`](https://github.com/TGSAI/segy) package from TGS
and against Equinor's [`segyio`](https://github.com/equinor/segyio). Byte
positions are facts about a published standard, not anybody's code; no source
was copied from either project, and neither is a dependency.

OpenSEGY is not affiliated with or endorsed by the Society of Exploration
Geophysicists, which publishes the SEG-Y standard.
