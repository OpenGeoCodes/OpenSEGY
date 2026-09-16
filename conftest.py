"""Make the package importable without installing it.

The suite runs against the working tree, not against whatever happens to be in
site-packages, because a test that silently exercises an older installed copy is
worse than no test.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
