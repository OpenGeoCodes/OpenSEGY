"""The geometry of a survey, without reading a single sample.

Reads 240 bytes per trace and skips the rest, so a 40 GB volume costs a few
hundred megabytes rather than 40 GB.

    python examples/survey_geometry.py volume.sgy
"""
import sys

import numpy as np

import opensegy


def main(path: str) -> int:
    with opensegy.open(path) as segy:
        print(f"{path}: {segy.n_traces:,} traces\n")

        g = segy.header_table(["inline", "crossline", "cdp_x", "cdp_y",
                               "coordinate_scalar"])

        for name in ("inline", "crossline"):
            column = g[name]
            if not column.any():
                print(f"  {name:<12} not written in this file")
                continue
            print(f"  {name:<12} {column.min()} … {column.max()}   "
                  f"{np.unique(column).size} distinct")

        # The scalar is not decoration: negative divides, positive multiplies,
        # and a reader that forgets it is out by a factor of a hundred.
        scalar = int(g["coordinate_scalar"][0])
        x = np.array([opensegy.apply_coordinate_scalar(int(v), scalar) for v in g["cdp_x"]])
        y = np.array([opensegy.apply_coordinate_scalar(int(v), scalar) for v in g["cdp_y"]])
        print(f"\n  coordinate scalar {scalar}")
        print(f"  x  {x.min():,.2f} … {x.max():,.2f}")
        print(f"  y  {y.min():,.2f} … {y.max():,.2f}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
