"""`python -m opensegy` — inspect a file, or write the fixture set.

Deliberately thin. The command exists so that a person with a suspect SEG-Y can
get an answer in one line without writing a script, and so that the fixture set
can be handed to other tools.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, scan
from .fixtures import materialise


def _inspect(args) -> int:
    segy = scan(args.path)
    if args.json:
        json.dump(segy.to_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0

    b = segy.binary
    rows = [
        ("Revision declared", f"{segy.declared_revision[0]}.{segy.declared_revision[1]}"),
        ("Revision detected", f"{segy.detected_revision[0]}.{segy.detected_revision[1]}"),
        ("Byte order", f"{segy.endian.name.lower()} (from {segy.endian_source})"),
        ("File size", f"{segy.file_size:,} bytes" if segy.file_size else "unknown"),
        ("First trace at", f"byte {segy.data_start:,} ({segy.data_start_source})"),
        ("Traces", f"{segy.trace_count:,} ({segy.trace_count_source})"
                   if segy.trace_count is not None else "unknown"),
        ("Samples per trace", f"{segy.sample_count:,}" if segy.sample_count else "unknown"),
        ("Sample interval", str(segy.sample_interval)),
        ("Sample format", (b.reading("sample_format").interpretation
                           or str(segy.sample_format))),
        ("Trace length", f"{segy.trace_bytes:,} bytes" if segy.trace_bytes else "unknown"),
        ("Extended textual", str(len(segy.extended_textual))),
    ]
    width = max(len(k) for k, _ in rows)
    print(f"\n{args.path}\n")
    for key, value in rows:
        print(f"  {key.ljust(width)}  {value}")

    stanzas = [h for h in segy.extended_textual if h.stanza_label]
    if stanzas:
        print("\n  Stanzas")
        for h in stanzas:
            print(f"    record {h.index}: ({h.stanza_label})")

    if segy.findings:
        print(f"\n  Findings ({len(segy.findings)})")
        for f in segy.findings:
            where = f" [bytes {f.byte_range[0]}-{f.byte_range[1]}]" if f.byte_range else ""
            print(f"    {f.severity.value.upper():<7} {f.message}{where}")
    else:
        print("\n  No findings.")
    print()
    return 1 if segy.severity and segy.severity.value == "error" else 0


def _fixtures(args) -> int:
    written = materialise(args.directory)
    for path in written:
        print(path)
    print(f"\n{len(written)} fixtures written to {args.directory}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opensegy", description="Modern open-source toolkit for SEG-Y")
    parser.add_argument("--version", action="version", version=f"opensegy {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="describe a SEG-Y file's structure")
    p_inspect.add_argument("path")
    p_inspect.add_argument("--json", action="store_true", help="machine-readable output")
    p_inspect.set_defaults(func=_inspect)

    p_fix = sub.add_parser("fixtures", help="write the synthetic fixture set to a directory")
    p_fix.add_argument("directory")
    p_fix.set_defaults(func=_fixtures)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
