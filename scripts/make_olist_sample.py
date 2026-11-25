"""Write the first N data rows (default 100) of each Olist CSV to
data/sample/olist/ so the loader can be tested without the full dataset.

Usage: python scripts/make_olist_sample.py [--src data/olist] [--dst data/sample/olist] [--rows 100]
"""

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from load.olist_loader import FILES  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=str(ROOT / "data" / "olist"))
    parser.add_argument("--dst", default=str(ROOT / "data" / "sample" / "olist"))
    parser.add_argument("--rows", type=int, default=100)
    args = parser.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)

    for name in FILES:
        with (src / name).open("r", encoding="utf-8-sig", newline="") as fin, (
            dst / name
        ).open("w", encoding="utf-8", newline="") as fout:
            reader = csv.reader(fin)
            writer = csv.writer(fout, lineterminator="\n")
            writer.writerow(next(reader))
            count = 0
            for row in reader:
                if not row:
                    continue
                writer.writerow(row)
                count += 1
                if count >= args.rows:
                    break
        print(f"{name}: {count} rows")


if __name__ == "__main__":
    main()