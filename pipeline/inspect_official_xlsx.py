from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]


def cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    kind = cell.attrib.get("t")
    value = next((item for item in cell if item.tag.endswith("}v")), None)
    if kind == "inlineStr":
        return "".join(item.text or "" for item in cell.iter() if item.tag.endswith("}t"))
    text = "" if value is None else value.text or ""
    if kind == "s" and text.isdigit():
        return shared_strings[int(text)]
    return text


def main() -> None:
    for path in sorted((ROOT / "입시결과_공식").rglob("*.xlsx")):
        print(f"\nFILE {path.relative_to(ROOT)}")
        with ZipFile(path) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(item.text or "" for item in string.iter() if item.tag.endswith("}t"))
                    for string in root
                ]
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {relation.attrib["Id"]: relation.attrib["Target"] for relation in relations}
            for sheet in (item for item in workbook.iter() if item.tag.endswith("}sheet")):
                relation_id = next(value for key, value in sheet.attrib.items() if key.endswith("}id"))
                target = targets[relation_id].lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                root = ET.fromstring(archive.read(target))
                matches: list[tuple[str | None, str]] = []
                all_rows: list[tuple[int, str]] = []
                for row in (item for item in root.iter() if item.tag.endswith("}row")):
                    values = [cell_text(cell, shared_strings) for cell in row if cell.tag.endswith("}c")]
                    line = " | ".join(values)
                    all_rows.append((int(row.attrib.get("r", "0")), line))
                    if "특성화" in line:
                        matches.append((row.attrib.get("r"), line))
                print(f"SHEET {sheet.attrib['name']} matches={len(matches)}")
                for row_number, line in matches[:20]:
                    print(f"  row={row_number} {line}")
                if path.parent.name == "가천대" and sheet.attrib["name"] == "Sheet1":
                    for row_number, line in all_rows:
                        if row_number <= 12 or 265 <= row_number <= 272:
                            print(f"  context row={row_number} {line}")
                if "특성화고교졸업자" in sheet.attrib["name"]:
                    for row_number, line in all_rows[:35]:
                        print(f"  context row={row_number} {line}")


if __name__ == "__main__":
    main()
