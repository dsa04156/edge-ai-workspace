"""Make the operator importable before collecting any standalone test file."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
