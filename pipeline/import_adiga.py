from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from lxml import html

from build_database import DB_PATH, field_group, normalize_program, valid_program
from import_official_xlsx import export_web
from inspect_adiga_tables import clean, table_grid


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "adiga_sources.json"
TARGET_PATTERN = re.compile(r"특성화\s*(?:고(?:교)?\s*(?:졸업자|출신자|동일계)?|교과)")
WORKER_PATTERN = re.compile(r"재직자")
NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def number(value: str) -> float | None:
    match = NUMBER_PATTERN.search(value.replace(",", ""))
    return float(match.group()) if match else None


def header_labels(rows: list[list[str]], count: int) -> list[str]:
    width = max((len(row) for row in rows), default=0)
    labels = []
    for column in range(width):
        parts = []
        for row in rows[:count]:
            value = clean(row[column]) if column < len(row) else ""
            if value and (not parts or value != parts[-1]):
                parts.append(value)
        labels.append(" / ".join(parts))
    return labels


def locate_table(rows: list[list[str]]) -> tuple[int, int, list[str]] | None:
    if len(rows) < 2:
        return None
    probe_count = min(7, len(rows))
    program_column = None
    for column in range(max(map(len, rows[:probe_count]), default=0)):
        values = [re.sub(r"\s+", "", row[column]) for row in rows[:probe_count] if column < len(row)]
        if any("모집단위" in value or "학과명" in value for value in values):
            program_column = column
            break
    if program_column is None:
        return None
    data_start = None
    for index, row in enumerate(rows):
        program = clean(row[program_column]) if program_column < len(row) else ""
        numeric_cells = sum(number(cell) is not None for cell in row)
        if index > 0 and program and "모집단위" not in re.sub(r"\s+", "", program) and "학과명" not in program and numeric_cells:
            data_start = index
            break
    if data_start is None:
        return None
    return program_column, data_start, header_labels(rows, data_start)


def metric_for(label: str, value: str) -> dict | None:
    parsed = number(value)
    if parsed is None:
        return None
    compact = re.sub(r"\s+", "", label).lower()
    code = None
    unit = None
    percentile = None
    stage = "final_registered" if "최종" in compact or "등록" in compact else None
    if "모집인원" in compact:
        code, unit = "quota", "people"
    elif "지원인원" in compact:
        code, unit = "applicants", "people"
    elif "경쟁률" in compact:
        code, unit = "competition_rate", "ratio"
    elif "충원" in compact and ("순위" in compact or "합격" in compact):
        code, unit = "waitlist_rank", "rank"
    elif ("등급" in compact or "내신" in compact or "학생부" in compact) and 0.5 <= parsed <= 9.5:
        unit = "grade"
        if "70" in compact or "75" in compact:
            code, percentile = "grade_70_cut", 70.0
        elif "50" in compact:
            code, percentile = "grade_50_cut", 50.0
        elif "평균" in compact:
            code = "grade_final_average" if stage else "grade_average"
        elif "최고" in compact:
            code = "grade_best"
        elif "최저" in compact:
            code = "grade_worst"
    if not code:
        return None
    return {"code": code, "label": label, "value": parsed, "unit": unit, "percentile": percentile, "stage": stage}


def parse_source(path: Path) -> list[dict]:
    document = html.fromstring(path.read_text(encoding="utf-8"))
    parsed: list[dict] = []
    for table_index, table in enumerate(document.xpath("//table")):
        rows = table_grid(table)
        located = locate_table(rows)
        if not located:
            continue
        program_column, data_start, labels = located
        track_columns = [index for index, label in enumerate(labels) if TARGET_PATTERN.search(label) and not WORKER_PATTERN.search(label)]
        track_column = next((index for index, label in enumerate(labels) if "전형" in label and "전형방법" not in label), None)
        target_table = bool(track_columns)
        if not target_table and track_column is None:
            continue
        for row_index, row in enumerate(rows[data_start:], start=data_start):
            program = clean(row[program_column]) if program_column < len(row) else ""
            if not program or program in {"합계", "총계", "대학계", "전체"} or len(program) > 120 or not valid_program(program):
                continue
            row_track = clean(row[track_column]) if track_column is not None and track_column < len(row) else ""
            if target_table:
                track = next((label.split("/")[0].strip() for label in labels if TARGET_PATTERN.search(label)), "특성화고교졸업자")
                metric_columns = track_columns
            elif TARGET_PATTERN.search(row_track) and not WORKER_PATTERN.search(row_track):
                track = row_track
                metric_columns = list(range(len(labels)))
            else:
                continue
            metrics = []
            for column in metric_columns:
                if column == program_column or column >= len(row):
                    continue
                metric = metric_for(labels[column], row[column])
                if metric:
                    metrics.append(metric)
            if metrics:
                parsed.append({"track": track, "program": program, "table": table_index, "row": row_index, "metrics": metrics, "raw": row})
    return parsed


def has_results(connection: sqlite3.Connection, university: str) -> bool:
    return bool(connection.execute("""
        SELECT 1 FROM institutions i JOIN documents d ON d.institution_id=i.id
        JOIN admission_tracks t ON t.document_id=d.id JOIN results r ON r.track_id=t.id
        WHERE i.source_name=? OR i.canonical_name=? LIMIT 1
    """, (university, university)).fetchone())


def insert_source(connection: sqlite3.Connection, source: dict, rows: list[dict]) -> int:
    university = source["university"]
    institution = connection.execute("SELECT id FROM institutions WHERE canonical_name=?", (university,)).fetchone()
    if institution:
        institution_id = institution[0]
    else:
        institution_id = connection.execute(
            "INSERT INTO institutions(source_name, canonical_name, campus) VALUES (?, ?, ?)",
            (source["adiga_label"], university, re.search(r"\(([^)]+)\)", university).group(1) if "(" in university else None),
        ).lastrowid
    path = ROOT / source["local_path"]
    document_id = connection.execute(
        "INSERT INTO documents(institution_id, admission_year, admission_cycle, local_path, source_url, sha256, page_count) VALUES (?, 2024, '수시', ?, ?, ?, 1)",
        (institution_id, source["local_path"], source["detail_url"], hashlib.sha256(path.read_bytes()).hexdigest()),
    ).lastrowid
    inserted = 0
    track_ids: dict[str, int] = {}
    program_ids: dict[str, int] = {}
    for item in rows:
        if item["track"] not in track_ids:
            track_ids[item["track"]] = connection.execute(
                "INSERT INTO admission_tracks(document_id, name, is_employed_worker) VALUES (?, ?, 0)",
                (document_id, item["track"]),
            ).lastrowid
        normalized = normalize_program(item["program"])
        if not normalized:
            continue
        if normalized not in program_ids:
            existing = connection.execute(
                "SELECT id FROM programs WHERE institution_id=? AND normalized_name=?", (institution_id, normalized)
            ).fetchone()
            program_ids[normalized] = existing[0] if existing else connection.execute(
                "INSERT INTO programs(institution_id, name, normalized_name, field_group) VALUES (?, ?, ?, ?)",
                (institution_id, item["program"], normalized, field_group(item["program"])),
            ).lastrowid
        metric_values = {metric["code"]: metric["value"] for metric in item["metrics"]}
        priority = ["grade_70_cut", "grade_final_average", "grade_average", "grade_50_cut", "grade_worst"]
        basis = next((code for code in priority if code in metric_values), None)
        cursor = connection.execute(
            """INSERT INTO results(track_id, program_id, page_number, table_index, row_index, reported_year,
                 quota, applicants, competition_rate, waitlist_rank, representative_grade,
                 representative_grade_basis, extraction_confidence, raw_row_json)
               VALUES (?, ?, 1, ?, ?, 2024, ?, ?, ?, ?, ?, ?, 0.96, ?)""",
            (track_ids[item["track"]], program_ids[normalized], item["table"], item["row"],
             int(metric_values["quota"]) if "quota" in metric_values else None,
             int(metric_values["applicants"]) if "applicants" in metric_values else None,
             metric_values.get("competition_rate"),
             int(metric_values["waitlist_rank"]) if "waitlist_rank" in metric_values else None,
             metric_values.get(basis) if basis else None, basis, json.dumps(item["raw"], ensure_ascii=False)),
        )
        for metric in item["metrics"]:
            connection.execute(
                "INSERT INTO metrics(result_id, metric_code, source_label, value_numeric, unit, percentile, stage) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cursor.lastrowid, metric["code"], metric["label"], metric["value"], metric["unit"], metric["percentile"], metric["stage"]),
            )
        inserted += 1
    return inserted


def main() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["sources"]
    connection = sqlite3.connect(DB_PATH)
    used_codes: set[str] = set()
    summary = []
    for source in registry:
        code = source["adiga_code"]
        if not code or not source["local_path"] or has_results(connection, source["university"]):
            continue
        if code in used_codes or connection.execute("SELECT 1 FROM documents WHERE local_path=?", (source["local_path"],)).fetchone():
            summary.append({"university": source["university"], "status": "ambiguous_shared_code", "rows": 0})
            continue
        used_codes.add(code)
        rows = parse_source(ROOT / source["local_path"])
        inserted = insert_source(connection, source, rows) if rows else 0
        summary.append({"university": source["university"], "status": "imported" if inserted else "no_target_result", "rows": inserted})
    connection.commit()
    web_summary = export_web(connection)
    connection.close()
    output = {"imported_universities": sum(row["status"] == "imported" for row in summary),
              "imported_rows": sum(row["rows"] for row in summary), "web": web_summary, "universities": summary}
    (ROOT / "data" / "adiga_import_report.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("imported_universities", "imported_rows", "web")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
