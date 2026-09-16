# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org).

## 0.1.0 — 2026-09-16

First release. Structure, headers and trace data.

### Reading

- **Revision detection**, 0 through 2.1, with the declared value and the value
  implied by the file's own structure kept apart and reported separately. Each
  structural signal carries its strength and the bytes it came from.
- **The complete binary file header**, per revision, as byte-ranged readings.
  The table is revision-dependent by more than addition: between 2.0 and 2.1 the
  field at byte 3507 narrowed from int32 to int16 and bytes 3509-3510 became the
  survey type, so the revision is settled before the table is chosen.
- **Byte order** read from the constant revision 2 put at bytes 3297-3300, and
  determined by plausibility for older files. Little-endian throughout.
- **Textual headers** in EBCDIC cp037, cp500, ASCII or latin-1, with the encoding
  chosen by result rather than assumed, cut into 80-column cards.
- **Extended textual headers**, including variable-length runs terminated by the
  end-text stanza, and runs a file carries without declaring. Stanza opening
  lines are recognised for any namespace and preserved; their contents are not
  parsed yet.
- **Where the trace data actually starts**, instead of assuming byte 3600. When
  the file contradicts itself, the tie-breaker is the offset from which the rest
  divides into whole traces.
- **The standard 240-byte trace header**, all 89 fields, plus the additional
  headers revision 2 permits. The table is not restricted by the declared
  revision, because plenty of files that declare revision 0 carry an inline at
  byte 189 anyway.
- **The revision 2 data trailer**, excluded from the trace arithmetic rather than
  counted as traces.
- **Trace samples** as float32 whatever the file holds — every sample format code
  the standard defines, including IBM hexadecimal float and the three-byte
  integers revision 2 added.
- **`header_table`**: named trace-header fields for many traces as columns,
  reading 240 bytes per trace and no samples.
- **Findings** with three severities, a stable code, a sentence of English and
  the byte range they came from.

### Writing

- `SegyBuilder` produces SEG-Y through the same field tables the parser reads
  through. Every argument beginning `declared_` writes a value into the header
  without changing what is produced, which is how a deliberately inconsistent
  file is made. Writing is strict; reading is tolerant.
- A 19-file fixture set covering revisions 0 through 2.1, both byte orders and
  seven named defects, generated rather than checked in.

### Interfaces

- `python -m opensegy inspect FILE [--json]` and `python -m opensegy fixtures DIR`.
- Byte sources are injected: a path, a `bytes`, or anything with
  `read(offset, length)` and `.size`. The library opens no URLs and imports no
  storage client.

### Verification

Every sample and every trace header of 21 real SEG-Y deliveries from Brazil's
national agency, revisions 0 and 1, is bit-for-bit identical to what segyio
reads. 228 tests.
