from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pdfplumber


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf")
    parser.add_argument("page", type=int)
    args = parser.parse_args()
    path = Path(args.pdf)
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[args.page - 1]
        variants = {
            "lines": {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
            "text": {
                "vertical_strategy": "text",
                "horizontal_strategy": "text",
                "intersection_tolerance": 8,
                "snap_tolerance": 5,
            },
        }
        output = {name: page.extract_tables(settings) for name, settings in variants.items()}
        output["layout_text"] = page.extract_text(layout=True)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
