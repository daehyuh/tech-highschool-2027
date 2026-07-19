from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pdfplumber

from build_database import DB_PATH, WEB_DATA_PATH, field_group, normalize_program


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ROOT = ROOT / "입시결과_공식"
NESIN_ROOT = ROOT / "입시결과_PDF"


def column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference).group()
    value = 0
    for letter in letters:
        value = value * 26 + ord(letter) - 64
    return value - 1


def workbook_rows(path: Path) -> dict[str, list[tuple[int, list[str]]]]:
    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(item.text or "" for item in string.iter() if item.tag.endswith("}t"))
                for string in root
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {relation.attrib["Id"]: relation.attrib["Target"] for relation in relations}
        output: dict[str, list[tuple[int, list[str]]]] = {}
        for sheet in (item for item in workbook.iter() if item.tag.endswith("}sheet")):
            relation_id = next(value for key, value in sheet.attrib.items() if key.endswith("}id"))
            target = targets[relation_id].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            root = ET.fromstring(archive.read(target))
            rows: list[tuple[int, list[str]]] = []
            for row in (item for item in root.iter() if item.tag.endswith("}row")):
                values: dict[int, str] = {}
                for cell in (item for item in row if item.tag.endswith("}c")):
                    kind = cell.attrib.get("t")
                    value = next((item for item in cell if item.tag.endswith("}v")), None)
                    text = "" if value is None else value.text or ""
                    if kind == "s" and text.isdigit():
                        text = shared[int(text)]
                    elif kind == "inlineStr":
                        text = "".join(item.text or "" for item in cell.iter() if item.tag.endswith("}t"))
                    values[column_index(cell.attrib["r"])] = text.strip()
                width = max(values, default=-1) + 1
                rows.append((int(row.attrib.get("r", "0")), [values.get(index, "") for index in range(width)]))
            output[sheet.attrib["name"]] = rows
        return output


def number(value: str) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def grade_metric(code: str, label: str, value: str, stage: str | None = None) -> dict | None:
    parsed = number(value)
    if parsed is None or not 0.5 <= parsed <= 9.5:
        return None
    return {"code": code, "label": label, "value": parsed, "unit": "grade", "stage": stage}


def gachon_results(path: Path) -> list[dict]:
    rows = workbook_rows(path)["Sheet1"]
    medical_programs = re.compile(r"의료산업|간호|치위생|방사선|물리치료|응급구조|의예|약학")
    output = []
    for row_number, cells in rows:
        if len(cells) < 8 or "특성화고교" not in cells[1]:
            continue
        program = cells[2]
        metrics = [
            grade_metric("grade_best", "등록자 최고등급", cells[5]),
            grade_metric("grade_average", "등록자 평균등급", cells[6]),
            grade_metric("grade_worst", "등록자 최저등급", cells[7]),
        ]
        output.append({
            "university": "가천대(메디컬)" if medical_programs.search(program) else "가천대",
            "track": cells[1], "program": program, "row": row_number,
            "quota": number(cells[3]), "competition_rate": number(cells[4]),
            "metrics": [metric for metric in metrics if metric], "raw": cells,
        })
    return output


def gangneung_results(path: Path) -> list[dict]:
    sheets = workbook_rows(path)
    sheet_name = next(name for name in sheets if "특성화고교졸업자" in name)
    output = []
    for row_number, cells in sheets[sheet_name]:
        if row_number < 4 or len(cells) < 3 or not cells[1]:
            continue
        metrics = []
        mappings = [
            (9, "grade_initial_average", "최초합격자 평균등급", "initial"),
            (11, "grade_50_cut", "최초합격자 50%컷", "initial"),
            (12, "grade_75_cut", "최초합격자 75%컷", "initial"),
            (21, "grade_final_average", "최종등록자 평균등급", "final_registered"),
            (23, "grade_final_50_cut", "최종등록자 50%컷", "final_registered"),
            (24, "grade_final_75_cut", "최종등록자 75%컷", "final_registered"),
        ]
        for index, code, label, stage in mappings:
            metric = grade_metric(code, label, cells[index] if index < len(cells) else "", stage)
            if metric:
                metrics.append(metric)
        output.append({
            "university": "국립강릉원주대", "track": sheet_name, "program": cells[1],
            "row": row_number, "quota": number(cells[2]),
            "competition_rate": number(cells[5]) if len(cells) > 5 else None,
            "metrics": metrics, "raw": cells,
        })
    return output


def gunsan_results(path: Path) -> list[dict]:
    """Read the vocational-high-school rows from Gunsan's official workbook."""
    sheets = workbook_rows(path)
    sheet_name = next(name for name in sheets if "학생부교과" in name)
    output = []
    for row_number, cells in sheets[sheet_name]:
        if len(cells) < 7 or cells[1] != "특성화고교졸업자" or not cells[3]:
            continue
        metrics = [
            grade_metric("grade_final_average", "최종등록 평균등급", cells[10] if len(cells) > 10 else "", "final_registered"),
            grade_metric("grade_final_70_cut", "최종등록 70%컷 등급", cells[12] if len(cells) > 12 else "", "final_registered"),
        ]
        output.append({
            "university": "국립군산대", "track": cells[1], "program": cells[3],
            "row": row_number, "reported_year": int(number(cells[0]) or 2025),
            "quota": number(cells[4]), "applicants": number(cells[5]),
            "competition_rate": number(cells[6]),
            "registrants": number(cells[8]) if len(cells) > 8 else None,
            "metrics": [metric for metric in metrics if metric], "raw": cells,
        })
    return output


def pyeongtaek_results(path: Path) -> list[dict]:
    """Read PTU's published whole-track summary (department cells are suppressed)."""
    with pdfplumber.open(path) as document:
        table = document.pages[0].extract_tables()[0]
    summary = next(row for row in table if row[0] and "전형별 요약" in row[0])
    metrics = [
        grade_metric("grade_final_average", "평택대기준 최종등록 평균등급", summary[10], "final_registered"),
        grade_metric("grade_final_worst", "평택대기준 최종등록 최저등급", summary[11], "final_registered"),
        grade_metric("grade_all_subject_average", "전과목 최종등록 평균등급", summary[12], "final_registered"),
    ]
    return [{
        "university": "평택대", "track": "특성화고교졸업자특별전형",
        "program": "전형별 요약(전체 모집단위)", "row": len(table), "reported_year": 2025,
        "quota": number(summary[13]), "applicants": number(summary[14]),
        "competition_rate": number(summary[15].split(":", 1)[0].strip()),
        "waitlist_rank": number(summary[16]),
        "metrics": [metric for metric in metrics if metric], "raw": summary,
    }]


def hankyong_results(path: Path) -> list[dict]:
    """Read program-level vocational grades from HKN University's off-quota table."""
    with pdfplumber.open(path) as document:
        tables = document.pages[0].extract_tables()
    if len(tables) != 1 or len(tables[0]) < 3:
        raise ValueError("한경국립대 정원외전형 표 구조가 예상과 다릅니다.")

    table = tables[0]
    header = table[0]
    if len(header) < 3 or "특성화고교출신자" not in (header[2] or ""):
        raise ValueError("한경국립대 특성화고교출신자 열을 찾지 못했습니다.")

    output = []
    for row_index, cells in enumerate(table[2:], start=2):
        if len(cells) < 3 or not cells[1] or number(cells[2]) is None:
            continue
        metric = grade_metric(
            "grade_average",
            "특성화고교출신자 평균등급",
            cells[2],
            "final_registered",
        )
        if not metric:
            continue
        output.append({
            "university": "한경국립대",
            "track": "특성화고교출신자",
            "program": cells[1].replace("\n", "").strip(),
            "page": 1,
            "table_index": 0,
            "row": row_index,
            "reported_year": 2026,
            "quota": None,
            "competition_rate": None,
            "metrics": [metric],
            "raw": cells,
        })
    if len(output) != 9:
        raise ValueError(f"한경국립대 모집단위 9개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def donga_results(path: Path) -> list[dict]:
    """Read Dong-A's vocational-track table from the right half of PDF page 5."""
    with pdfplumber.open(path) as document:
        page = document.pages[4]
        page_text = page.extract_text() or ""
        if "특성화고교출신자(동일계)" not in page_text:
            raise ValueError("동아대 특성화고교출신자 표를 찾지 못했습니다.")
        tables = page.crop((page.width / 2, 0, page.width, page.height)).extract_tables()
    if len(tables) != 1 or len(tables[0]) < 3:
        raise ValueError("동아대 특성화고교출신자 표 구조가 예상과 다릅니다.")

    output = []
    for row_index, cells in enumerate(tables[0][2:], start=2):
        if len(cells) < 8 or not cells[1]:
            continue
        metrics = [
            grade_metric(
                "grade_final_best",
                "최종등록자 전교과 최고등급",
                cells[6] or "",
                "final_registered",
            ),
            grade_metric(
                "grade_final_average",
                "최종등록자 전교과 평균등급",
                cells[7] or "",
                "final_registered",
            ),
        ]
        output.append({
            "university": "동아대",
            "track": "특성화고교출신자(동일계)",
            "program": cells[1].replace("\n", ""),
            "page": 5,
            "table_index": 1,
            "row": row_index,
            "reported_year": 2026,
            "quota": number(cells[2]),
            "applicants": number(cells[3]),
            "competition_rate": number(cells[4]),
            "waitlist_rank": number(cells[5]),
            "metrics": [metric for metric in metrics if metric],
            "raw": cells,
        })
    if len(output) != 24:
        raise ValueError(f"동아대 모집단위 24개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def ulsan_results(path: Path) -> list[dict]:
    """Read Ulsan's vocational high-school rows from the official workbook."""
    sheets = workbook_rows(path)
    rows = sheets[next(name for name in sheets if "학생부교과" in name)]
    output = []
    in_track = False
    for row_number, cells in rows:
        if cells and cells[0].strip() == "특성화고교졸업자(정원외)전형":
            in_track = True
        elif in_track and cells and cells[0]:
            break
        if not in_track or len(cells) < 8 or not cells[1]:
            continue
        metrics = [
            grade_metric(
                "grade_final_average",
                "최종등록자 평균성적",
                cells[6],
                "final_registered",
            ),
            grade_metric(
                "grade_final_70_cut",
                "최종등록자 70%컷 성적",
                cells[7],
                "final_registered",
            ),
        ]
        output.append({
            "university": "울산대",
            "track": "특성화고교졸업자(정원외)전형",
            "program": cells[1],
            "row": row_number,
            "reported_year": 2026,
            "quota": number(cells[2]),
            "applicants": number(cells[3]),
            "competition_rate": number(cells[4]),
            "waitlist_rank": number(cells[5]),
            "metrics": [metric for metric in metrics if metric],
            "raw": cells,
        })
    if len(output) != 10:
        raise ValueError(f"울산대 모집단위 10개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def tongmyong_results(path: Path) -> list[dict]:
    """Read Tongmyong's vocational-subject column from the one-page result table."""
    with pdfplumber.open(path) as document:
        tables = document.pages[0].extract_tables()
    if len(tables) != 1 or len(tables[0]) < 3:
        raise ValueError("동명대 입시결과 표 구조가 예상과 다릅니다.")

    table = tables[0]
    if "특성화고교과" not in (table[0][9] or ""):
        raise ValueError("동명대 특성화고교과 열을 찾지 못했습니다.")
    output = []
    for row_index, cells in enumerate(table[2:], start=2):
        if len(cells) < 13 or not cells[0] or number(cells[9]) is None:
            continue
        metrics = [
            grade_metric("grade_final_average", "특성화고교과 최종등록자 평균등급", cells[10] or "", "final_registered"),
            grade_metric("grade_final_70_cut", "특성화고교과 최종등록자 70% CUT", cells[11] or "", "final_registered"),
        ]
        if not any(metrics):
            continue
        output.append({
            "university": "동명대", "track": "특성화고교과", "program": cells[0].replace("\n", ""),
            "page": 1, "table_index": 0, "row": row_index, "reported_year": 2026,
            "quota": None, "competition_rate": number(cells[9]), "waitlist_rank": number(cells[12]),
            "metrics": [metric for metric in metrics if metric], "raw": cells,
        })
    if len(output) != 34:
        raise ValueError(f"동명대 모집단위 34개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def daejin_results(path: Path) -> list[dict]:
    """Read Daejin's vocational graduate columns from the off-quota result table."""
    with pdfplumber.open(path) as document:
        tables = document.pages[4].extract_tables()
    if len(tables) != 1 or len(tables[0]) < 3:
        raise ValueError("대진대 정원외 입시결과 표 구조가 예상과 다릅니다.")

    output = []
    for row_index, cells in enumerate(tables[0][2:], start=2):
        if len(cells) < 13 or not (cells[1] or cells[2]) or (cells[1] or "").strip() == "대학 계":
            continue
        if number(cells[8]) is None or number(cells[12]) is None:
            continue
        program = " ".join(part.replace("\n", "") for part in (cells[1], cells[2]) if part).strip()
        metric = grade_metric("grade_final_average", "특성화고교졸업자 최종등록자 학생부 평균등급", cells[12], "final_registered")
        output.append({
            "university": "대진대", "track": "특성화고교졸업자", "program": program,
            "page": 5, "table_index": 0, "row": row_index, "reported_year": 2026,
            "quota": number(cells[8]), "applicants": number(cells[9]),
            "competition_rate": number(cells[10]), "waitlist_rank": number(cells[11]),
            "metrics": [metric] if metric else [], "raw": cells,
        })
    if len(output) != 9:
        raise ValueError(f"대진대 모집단위 9개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def sungkyul_results(path: Path) -> list[dict]:
    """Read Sungkyul's in-quota and off-quota vocational graduate rows."""
    output = []
    with pdfplumber.open(path) as document:
        for page_number in (5, 6):
            tables = document.pages[page_number - 1].extract_tables()
            if len(tables) != 1:
                raise ValueError(f"성결대 {page_number}쪽 표 구조가 예상과 다릅니다.")
            for row_index, cells in enumerate(tables[0][1:], start=1):
                if len(cells) < 8 or not cells[0] or "특성화고교졸업자" not in cells[0]:
                    continue
                metric = grade_metric("grade_final_70_cut", "최종합격자 학생부 70% CUT", cells[6], "final_registered")
                if not metric:
                    continue
                output.append({
                    "university": "성결대", "track": cells[0], "program": cells[1],
                    "page": page_number, "table_index": 0, "row": row_index, "reported_year": 2026,
                    "quota": number(cells[2]), "applicants": number(cells[3]),
                    "competition_rate": number(cells[4]), "waitlist_rank": number(cells[7]),
                    "metrics": [metric], "raw": cells,
                })
    if len(output) != 17:
        raise ValueError(f"성결대 모집단위 17개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def hanshin_results(path: Path) -> list[dict]:
    """Read Hanshin's vocational graduate table on page 8."""
    with pdfplumber.open(path) as document:
        tables = document.pages[7].extract_tables()
    table = next((table for table in tables if table and "특성화고교졸업자" in (table[0][0] or "")), None)
    if table is None:
        raise ValueError("한신대 특성화고교졸업자 표를 찾지 못했습니다.")

    output = []
    for row_index, cells in enumerate(table[2:], start=2):
        if len(cells) < 8 or not cells[1] or cells[1] == "계" or number(cells[7]) is None:
            continue
        program = cells[1].replace("\n", "")
        metrics = [
            grade_metric("grade_final_best", "최종등록자 최고등급", cells[6], "final_registered"),
            grade_metric("grade_final_average", "최종등록자 평균등급", cells[7], "final_registered"),
        ]
        output.append({
            "university": "한신대", "track": "특성화고교졸업자전형(정원외)", "program": program,
            "page": 8, "table_index": 2, "row": row_index, "reported_year": 2026,
            "quota": number(cells[2]), "applicants": number(cells[3]),
            "competition_rate": number(cells[4]), "waitlist_rank": number(cells[5]),
            "metrics": [metric for metric in metrics if metric], "raw": cells,
        })
    if len(output) != 4:
        raise ValueError(f"한신대 모집단위 4개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def ensure_institution(connection: sqlite3.Connection, university: str) -> int:
    row = connection.execute("SELECT id FROM institutions WHERE canonical_name = ?", (university,)).fetchone()
    if row:
        return row[0]
    cursor = connection.execute(
        "INSERT INTO institutions(source_name, canonical_name, campus) VALUES (?, ?, ?)",
        (university, university, re.search(r"\(([^)]+)\)", university).group(1) if "(" in university else None),
    )
    return cursor.lastrowid


def insert_document(
    connection: sqlite3.Connection, university: str, path: Path, source_url: str,
    admission_year: int = 2026, admission_cycle: str = "수시",
) -> int:
    institution_id = ensure_institution(connection, university)
    relative_path = path.relative_to(ROOT).as_posix()
    row = connection.execute("SELECT id FROM documents WHERE local_path = ?", (relative_path,)).fetchone()
    if row:
        return row[0]
    page_count = 1
    if path.suffix.lower() == ".pdf":
        with pdfplumber.open(path) as document:
            page_count = len(document.pages)
    cursor = connection.execute(
        "INSERT INTO documents(institution_id, admission_year, admission_cycle, local_path, source_url, sha256, page_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            institution_id,
            admission_year,
            admission_cycle,
            relative_path,
            source_url,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            page_count,
        ),
    )
    return cursor.lastrowid


def insert_results(connection: sqlite3.Connection, document_id: int, rows: list[dict]) -> None:
    institution_id = connection.execute("SELECT institution_id FROM documents WHERE id = ?", (document_id,)).fetchone()[0]
    for item in rows:
        track = connection.execute("SELECT id FROM admission_tracks WHERE document_id = ? AND name = ?", (document_id, item["track"])).fetchone()
        if not track:
            track_id = connection.execute(
                "INSERT INTO admission_tracks(document_id, name, is_employed_worker) VALUES (?, ?, 0)",
                (document_id, item["track"]),
            ).lastrowid
        else:
            track_id = track[0]
        normalized = normalize_program(item["program"])
        program = connection.execute(
            "SELECT id FROM programs WHERE institution_id = ? AND normalized_name = ?", (institution_id, normalized)
        ).fetchone()
        if not program:
            program_id = connection.execute(
                "INSERT INTO programs(institution_id, name, normalized_name, field_group) VALUES (?, ?, ?, ?)",
                (institution_id, item["program"], normalized, field_group(item["program"])),
            ).lastrowid
        else:
            program_id = program[0]
        metric_values = {metric["code"]: metric["value"] for metric in item["metrics"]}
        priority = ["grade_final_average", "grade_final_70_cut", "grade_final_75_cut", "grade_average", "grade_75_cut", "grade_worst", "grade_initial_average"]
        basis = next((code for code in priority if code in metric_values), None)
        cursor = connection.execute(
            """INSERT OR IGNORE INTO results(
              track_id, program_id, page_number, table_index, row_index, reported_year, quota, applicants,
              competition_rate, registrants, waitlist_rank, representative_grade, representative_grade_basis,
              extraction_confidence, raw_row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.98, ?)""",
            (track_id, program_id, item.get("page", 1), item.get("table_index", 0),
             item["row"], item.get("reported_year", 2026),
             int(item["quota"]) if item["quota"] is not None else None,
             int(item["applicants"]) if item.get("applicants") is not None else None,
             item["competition_rate"],
             int(item["registrants"]) if item.get("registrants") is not None else None,
             int(item["waitlist_rank"]) if item.get("waitlist_rank") is not None else None,
             metric_values.get(basis) if basis else None, basis,
             json.dumps(item["raw"], ensure_ascii=False)),
        )
        # sqlite3.lastrowid can retain the id from an earlier INSERT when
        # INSERT OR IGNORE skips this result. rowcount is the authoritative
        # signal that a new result row was created and may receive metrics.
        if cursor.rowcount == 0:
            continue
        for metric in item["metrics"]:
            connection.execute(
                "INSERT INTO metrics(result_id, metric_code, source_label, value_numeric, unit, stage) VALUES (?, ?, ?, ?, ?, ?)",
                (cursor.lastrowid, metric["code"], metric["label"], metric["value"], metric["unit"], metric["stage"]),
            )


def export_web(connection: sqlite3.Connection) -> dict:
    query = """
      SELECT r.id, i.source_name, i.canonical_name, COALESCE(r.reported_year, d.admission_year) AS admission_year,
             t.name AS track_name, p.name AS program_name, p.field_group, r.quota, r.applicants, r.competition_rate,
             r.registrants, r.waitlist_rank, r.representative_grade, r.representative_grade_basis,
             r.extraction_confidence, r.page_number, d.local_path, d.source_url
      FROM results r JOIN admission_tracks t ON t.id=r.track_id JOIN documents d ON d.id=t.document_id
      JOIN institutions i ON i.id=d.institution_id JOIN programs p ON p.id=r.program_id
      WHERE t.is_employed_worker=0 ORDER BY admission_year DESC, i.source_name, p.name
    """
    columns = [item[0] for item in connection.execute(query).description]
    results = [dict(zip(columns, row)) for row in connection.execute(query)]
    metrics: dict[int, list[dict]] = {}
    for row in connection.execute("SELECT result_id, metric_code, source_label, value_numeric, unit, percentile, stage FROM metrics ORDER BY id"):
        metrics.setdefault(row[0], []).append({"code": row[1], "label": row[2], "value": row[3], "unit": row[4], "percentile": row[5], "stage": row[6]})
    for row in results:
        row["metrics"] = metrics.get(row["id"], [])
    payload = {"generated_from": "2027 특성화고 모집대학 원본, 수집 PDF 및 대학 공식 입시결과",
               "summary": {"result_count": len(results),
                           "institution_count": len({row["canonical_name"] for row in results}),
                           "program_count": len({(row["canonical_name"], row["program_name"]) for row in results}),
                           "grade_result_count": sum(row["representative_grade"] is not None for row in results)},
               "results": results}
    WEB_DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload["summary"]


def main() -> None:
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    gachon_path = OFFICIAL_ROOT / "가천대" / "2026_수시_입시결과.xlsx"
    gachon = gachon_results(gachon_path)
    for university in ("가천대", "가천대(메디컬)"):
        rows = [row for row in gachon if row["university"] == university]
        document_path = gachon_path
        if university.endswith("(메디컬)"):
            document_path = OFFICIAL_ROOT / "가천대" / "2026_수시_입시결과_메디컬.xlsx"
        document_id = insert_document(
            connection, university, document_path,
            "https://admission.gachon.ac.kr/admission/html/counsel/resultView.asp?BOARD_IDX=30155",
        )
        insert_results(connection, document_id, rows)
    gangneung_path = OFFICIAL_ROOT / "국립강릉원주대" / "2026_수시_입시결과.xlsx"
    document_id = insert_document(
        connection, "국립강릉원주대", gangneung_path,
        "https://admission.kangwon.ac.kr/admission/bbs/1153/detail.do?pstSn=534",
    )
    insert_results(connection, document_id, gangneung_results(gangneung_path))
    gunsan_path = OFFICIAL_ROOT / "국립군산대" / "2025_수시_입시결과.xlsx"
    document_id = insert_document(
        connection, "국립군산대", gunsan_path,
        "https://www.kunsan.ac.kr/iphak/board/view.kunsan?menuCd=DOM_000001218002000000&boardId=BBS_0000045&dataSid=1353093",
        admission_year=2025,
    )
    insert_results(connection, document_id, gunsan_results(gunsan_path))
    pyeongtaek_path = OFFICIAL_ROOT / "평택대" / "2025_수시_입시결과_정원외.pdf"
    document_id = insert_document(
        connection, "평택대", pyeongtaek_path,
        "https://entrance.ptu.ac.kr/entrance/3676/subview.do?enc=Zm5jdDF8QEB8JTJGYmJzJTJGZW50cmFuY2UlMkYzMDYlMkYzMTg0NSUyRmFydGNsVmlldy5kbyUzRg%3D%3D",
        admission_year=2025,
    )
    insert_results(connection, document_id, pyeongtaek_results(pyeongtaek_path))
    hankyong_path = OFFICIAL_ROOT / "한경국립대" / "2026_수시_정원외전형_입시결과.pdf"
    document_id = insert_document(
        connection,
        "한경국립대",
        hankyong_path,
        "https://ipsi.hknu.ac.kr/result/result.php",
        admission_year=2026,
    )
    insert_results(connection, document_id, hankyong_results(hankyong_path))
    donga_path = OFFICIAL_ROOT / "동아대" / "2026" / "2026학년도 학생부종합 입시결과.pdf"
    document_id = insert_document(
        connection,
        "동아대",
        donga_path,
        "https://ent.donga.ac.kr/admission/html/rolling/resultView.asp?BOARD_IDX=30600",
        admission_year=2026,
    )
    insert_results(connection, document_id, donga_results(donga_path))
    ulsan_path = OFFICIAL_ROOT / "울산대" / "2026_수시_입시결과_학생부교과.xlsx"
    document_id = insert_document(
        connection,
        "울산대",
        ulsan_path,
        "https://iphak.ulsan.ac.kr/main/46?action=view&no=16268",
        admission_year=2026,
    )
    insert_results(connection, document_id, ulsan_results(ulsan_path))
    nesin_imports = [
        (
            "동명대",
            NESIN_ROOT / "동명대" / "동명대학교" / "동명대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=189",
            tongmyong_results,
        ),
        (
            "대진대",
            NESIN_ROOT / "대진대" / "대진대학교" / "대진대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=51",
            daejin_results,
        ),
        (
            "성결대",
            NESIN_ROOT / "성결대" / "성결대학교" / "성결대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=55",
            sungkyul_results,
        ),
        (
            "한신대",
            NESIN_ROOT / "한신대" / "한신대학교" / "한신대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=77",
            hanshin_results,
        ),
    ]
    for university, path, source_url, parser in nesin_imports:
        document_id = insert_document(connection, university, path, source_url, admission_year=2026)
        insert_results(connection, document_id, parser(path))
    connection.commit()
    print(json.dumps(export_web(connection), ensure_ascii=False))
    connection.close()


if __name__ == "__main__":
    main()
