from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from lxml import html


ROOT = Path(__file__).resolve().parents[1]


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def table_grid(table) -> list[list[str]]:
    grid: list[list[str]] = []
    occupied: dict[tuple[int, int], str] = {}
    for row_index, tr in enumerate(table.xpath("./thead/tr|./tbody/tr|./tr")):
        row: list[str] = []
        column = 0
        for cell in tr.xpath("./th|./td"):
            while (row_index, column) in occupied:
                row.append(occupied[(row_index, column)])
                column += 1
            value = clean(cell.text_content())
            rowspan = int(cell.get("rowspan", "1") or 1)
            colspan = int(cell.get("colspan", "1") or 1)
            for offset in range(colspan):
                row.append(value)
                for down in range(1, rowspan):
                    occupied[(row_index + down, column + offset)] = value
            column += colspan
        while (row_index, column) in occupied:
            row.append(occupied[(row_index, column)])
            column += 1
        grid.append(row)
    width = max((len(row) for row in grid), default=0)
    return [row + [""] * (width - len(row)) for row in grid]


def main() -> None:
    registry = json.loads((ROOT / "data" / "adiga_sources.json").read_text(encoding="utf-8"))
    target_only = "--target-only" in sys.argv
    requested = {value for value in sys.argv[1:] if not value.startswith("--")}
    for source in registry["sources"]:
        if requested and source["university"] not in requested:
            continue
        if not source["local_path"]:
            continue
        document = html.fromstring((ROOT / source["local_path"]).read_text(encoding="utf-8"))
        matches = []
        for table_index, table in enumerate(document.xpath("//table")):
            text = clean(table.text_content())
            if target_only and "특성화고" not in text:
                continue
            if "모집" in text and any(term in text for term in ("경쟁률", "등급", "50%", "70%", "학생부")):
                preceding = clean(" ".join(table.xpath("preceding::*[self::p or self::h1 or self::h2 or self::h3 or self::h4][position() <= 4]/text()")))[-300:]
                matches.append((table_index, table_grid(table), preceding))
        print(f"\n{source['university']} {source['adiga_code']} candidate_tables={len(matches)}")
        for table_index, grid, preceding in matches:
            print(f" TABLE {table_index} rows={len(grid)} cols={max(map(len, grid), default=0)}")
            print(f"  CONTEXT {preceding}")
            for row in grid[:10]:
                print("  " + " | ".join(row))


if __name__ == "__main__":
    main()
