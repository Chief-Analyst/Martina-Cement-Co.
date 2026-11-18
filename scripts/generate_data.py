"""Write the synthetic tables to CSV, as a template for your own data.

    python scripts/generate_data.py            -> data/sample/*.csv
    python scripts/generate_data.py out_dir    -> out_dir/*.csv

Then set MC_DATA_SOURCE=csv and MC_DATA_DIR=<folder> in .env to run the
dashboard from the CSV files (edit them, or replace them with your own data
in the same columns; docs/data-dictionary.md describes every column).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from martina.data.synthetic import write_csv  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/sample")
    counts = write_csv(out)
    for name, n in counts.items():
        print(f"{name:14s} {n:>8,} rows")
    print(f"Written to {out.resolve()}")
