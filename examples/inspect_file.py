"""What is in this SEG-Y, and can I trust it?

    python examples/inspect_file.py survey.sgy
"""
import sys

import opensegy


def main(path: str) -> int:
    segy = opensegy.scan(path)

    print(f"{path}\n")
    print(f"  revision declared  {'.'.join(map(str, segy.declared_revision))}")
    print(f"  revision detected  {'.'.join(map(str, segy.detected_revision))}")
    print(f"  byte order         {segy.endian.name.lower()} (from {segy.endian_source})")
    print(f"  first trace at     byte {segy.data_start:,} ({segy.data_start_source})")
    print(f"  traces             {segy.trace_count:,} ({segy.trace_count_source})")
    print(f"  samples per trace  {segy.sample_count:,}")
    print(f"  sample format      {segy.binary.reading('sample_format').interpretation}")

    # Every value knows where it came from.
    fmt = segy.binary.reading("sample_format")
    print(f"\n  sample format came from bytes {fmt.start}-{fmt.end}, raw {fmt.hex}")

    for header in segy.extended_textual:
        if header.stanza_label:
            print(f"  extended textual header {header.index} opens ({header.stanza_label})")

    if segy.findings:
        print(f"\n  {len(segy.findings)} finding(s):")
        for f in segy.findings:
            where = f" [bytes {f.byte_range[0]}-{f.byte_range[1]}]" if f.byte_range else ""
            print(f"    {f.severity.value.upper():<7} {f.message}{where}")
    else:
        print("\n  No findings.")

    return 1 if segy.severity is opensegy.Severity.ERROR else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
