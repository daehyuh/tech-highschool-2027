from __future__ import annotations

import csv
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "2027_특성화고_모집대학.xlsm"
JSON_PATH = ROOT / "data" / "target_universities.json"
CSV_PATH = ROOT / "data" / "target_universities.csv"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = {"p": "http://schemas.openxmlformats.org/package/2006/relationships"}


def column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference).group()
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - 64
    return value - 1


def main() -> None:
    with zipfile.ZipFile(WORKBOOK) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(node.text or "" for node in item.findall(".//m:t", NS)) for item in shared_root.findall("m:si", NS)]
        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root.findall("p:Relationship", REL_NS)}
        sheets = []
        for sheet in workbook_root.findall("m:sheets/m:sheet", NS):
            name = sheet.attrib["name"]
            target = targets[sheet.attrib[f"{{{NS['r']}}}id"]].lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            root = ET.fromstring(archive.read(target))
            rows = []
            for row in root.findall("m:sheetData/m:row", NS):
                values: dict[int, str] = {}
                for cell in row.findall("m:c", NS):
                    index = column_index(cell.attrib["r"])
                    kind = cell.attrib.get("t")
                    value_node = cell.find("m:v", NS)
                    if kind == "inlineStr":
                        value = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
                    elif value_node is None:
                        value = ""
                    elif kind == "s":
                        value = shared[int(value_node.text)]
                    else:
                        value = value_node.text or ""
                    values[index] = value.strip()
                if values:
                    width = max(values) + 1
                    rows.append([values.get(index, "") for index in range(width)])
            sheets.append({"name": name, "rows": rows})

    parsed_sheets = []
    universities: dict[str, dict] = {}
    for sheet in sheets:
        rows = sheet["rows"]
        header_index = next(
            (index for index, row in enumerate(rows) if any("대학" in cell for cell in row) and len(row) >= 2),
            0,
        )
        headers = [cell or f"column_{index + 1}" for index, cell in enumerate(rows[header_index])]
        records = []
        for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
            padded = row + [""] * (len(headers) - len(row))
            record = {headers[index]: padded[index] for index in range(len(headers))}
            record["source_row"] = row_number
            if any(value for key, value in record.items() if key != "source_row"):
                records.append(record)
                university = record.get("대학", "").strip()
                if university:
                    item = universities.setdefault(
                        university,
                        {"university": university, "cycles": [], "regions": [], "source_rows": [], "records": []},
                    )
                    item["cycles"].append(sheet["name"])
                    if record.get("지역") and record["지역"] not in item["regions"]:
                        item["regions"].append(record["지역"])
                    item["source_rows"].append(f"{sheet['name']}!{row_number}")
                    item["records"].append(record)
        parsed_sheets.append({"name": sheet["name"], "headers": headers, "records": records})

    target_records = sorted(universities.values(), key=lambda item: item["university"])

    payload = {
        "workbook": WORKBOOK.name,
        "target_count": len(target_records),
        "targets": target_records,
        "sheets": parsed_sheets,
        "all_sheets": [{"name": sheet["name"], "row_count": len(sheet["rows"]), "preview": sheet["rows"][:8]} for sheet in sheets],
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as output:
        fieldnames = ["university", "cycles", "regions", "source_rows"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {
                "university": item["university"],
                "cycles": ", ".join(item["cycles"]),
                "regions": ", ".join(item["regions"]),
                "source_rows": ", ".join(item["source_rows"]),
            }
            for item in target_records
        )
    print(json.dumps({"target_count": len(target_records), "sheet_counts": {sheet["name"]: len(sheet["records"]) for sheet in parsed_sheets}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
