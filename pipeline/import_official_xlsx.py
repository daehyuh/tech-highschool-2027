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


def numeric_metric(code: str, label: str, value: str, unit: str, stage: str | None = None) -> dict | None:
    parsed = number(value)
    if parsed is None:
        return None
    return {"code": code, "label": label, "value": parsed, "unit": unit, "stage": stage}


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


def suwon_results(path: Path) -> list[dict]:
    """Read Suwon's vocational graduate rows, including the visually separated grade column."""
    with pdfplumber.open(path) as document:
        lines = (document.pages[8].extract_text(layout=True) or "").splitlines()
    row_pattern = re.compile(
        r"^\s*(.+?)\s+(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$"
    )
    output = []
    for row_index, line in enumerate(lines):
        match = row_pattern.match(line)
        if not match:
            continue
        prefix, quota, applicants, competition_rate, average_grade = match.groups()
        program = prefix.strip().split()[-1]
        metric = grade_metric("grade_average", "학생부성적 평균", average_grade)
        if not metric:
            continue
        output.append({
            "university": "수원대", "track": "특성화고졸업자전형", "program": program,
            "page": 9, "table_index": 0, "row": row_index, "reported_year": 2026,
            "quota": number(quota), "applicants": number(applicants),
            "competition_rate": number(competition_rate), "metrics": [metric], "raw": line,
        })
    if len(output) != 8:
        raise ValueError(f"수원대 모집단위 8개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def shinhan_results(path: Path) -> list[dict]:
    """Read Shinhan's vocational graduate grade and 1,000-point score columns."""
    with pdfplumber.open(path) as document:
        lines = (document.pages[9].extract_text(layout=True) or "").splitlines()
    row_pattern = re.compile(
        r"^\s*(.+?)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+"
        r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(-|\d+)\s*$"
    )
    output = []
    for row_index, line in enumerate(lines):
        match = row_pattern.match(line)
        if not match:
            continue
        program, quota, competition_rate, cutoff_grade, cutoff_score, average_grade, average_score, waitlist = match.groups()
        metrics = [
            grade_metric("grade_cutoff", "커트라인 등급", cutoff_grade, "final_registered"),
            numeric_metric("score_cutoff_1000", "커트라인 원점수(1000점 만점)", cutoff_score, "points", "final_registered"),
            grade_metric("grade_final_average", "최종등록자 평균등급", average_grade, "final_registered"),
            numeric_metric("score_final_average_1000", "최종등록자 평균 원점수(1000점 만점)", average_score, "points", "final_registered"),
        ]
        output.append({
            "university": "신한대", "track": "특성화고교졸업자전형", "program": program.strip(),
            "page": 10, "table_index": 1, "row": row_index, "reported_year": 2026,
            "quota": number(quota), "competition_rate": number(competition_rate),
            "waitlist_rank": number(waitlist), "metrics": [metric for metric in metrics if metric], "raw": line,
        })
    if len(output) != 8:
        raise ValueError(f"신한대 모집단위 8개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def kwangwoon_results(path: Path) -> list[dict]:
    """Read Kwangwoon's final-registrant 70% cut grades for the vocational track."""
    with pdfplumber.open(path) as document:
        tables = document.pages[9].extract_tables()
    table = next((table for table in tables if table and len(table[0]) == 10), None)
    if table is None or "학생부" not in (table[0][5] or ""):
        raise ValueError("광운대 특성화고졸업자 성적표를 찾지 못했습니다.")
    output = []
    for row_index, cells in enumerate(table[1:], start=1):
        if len(cells) < 9 or not cells[1]:
            continue
        metric = grade_metric("grade_final_70_cut", "최종등록자 학생부등급 70% 컷", cells[5], "final_registered")
        if not metric:
            continue
        output.append({
            "university": "광운대", "track": "학생부종합(특성화고졸업자전형)",
            "program": " / ".join(part.strip() for part in cells[1].splitlines() if part.strip()),
            "page": 10, "table_index": 1, "row": row_index, "reported_year": 2026,
            "quota": number(cells[2]), "applicants": number(cells[3]),
            "competition_rate": number(cells[4]), "waitlist_rank": number(cells[7]),
            "metrics": [metric], "raw": cells,
        })
    if len(output) != 8:
        raise ValueError(f"광운대 모집단위 8개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def duksung_results(path: Path) -> list[dict]:
    """Read Duksung's three published college-level vocational aggregates."""
    with pdfplumber.open(path) as document:
        competition_table = document.pages[8].extract_tables()[3]
        grade_table = document.pages[13].extract_tables()[2]
    competition = {
        row[0].replace("\n", " "): row[7:10]
        for row in competition_table[2:]
        if row[0] and len(row) >= 10 and number(row[7]) is not None
    }
    output = []
    for row_index, cells in enumerate(grade_table[3:], start=3):
        if len(cells) < 16 or not cells[0]:
            continue
        program = cells[0].replace("\n", " ")
        metrics = [
            grade_metric("grade_initial_average", "2026 최초합격자 등급평균", cells[11], "initial"),
            numeric_metric("score_final_average", "2026 최종등록자 환산평균", cells[12], "score", "final_registered"),
            grade_metric("grade_final_average", "2026 최종등록자 등급평균", cells[13], "final_registered"),
            grade_metric("grade_final_70_cut", "2026 최종등록자 70% CUT", cells[14], "final_registered"),
        ]
        quota, applicants, competition_rate = competition.get(program, (None, None, None))
        output.append({
            "university": "덕성여대", "track": "기회균형전형Ⅰ_특성화고교", "program": program,
            "page": 14, "table_index": 2, "row": row_index, "reported_year": 2026,
            "quota": number(quota), "applicants": number(applicants),
            "competition_rate": number(competition_rate), "waitlist_rank": number(cells[15]),
            "metrics": [metric for metric in metrics if metric], "raw": cells,
        })
    if len(output) != 3:
        raise ValueError(f"덕성여대 집계단위 3개를 예상했지만 {len(output)}개를 찾았습니다.")
    return output


def seoul_womens_results(path: Path) -> list[dict]:
    """Read Seoul Women's two published college-level vocational aggregates."""
    with pdfplumber.open(path) as document:
        text = document.pages[5].extract_text() or ""
    marker = "6) 학생부종합(기회균형전형_특성화고교졸업자)"
    if marker not in text:
        raise ValueError("서울여대 특성화고교졸업자 결과 구역을 찾지 못했습니다.")
    section = text.split(marker, 1)[1]
    definitions = [
        ("사회과학대학", r"사회과학대학\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"),
        ("과학기술융합대학, 미래산업융합대학", r"과학기술융합대학,\s*(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"),
    ]
    output = []
    for row_index, (program, pattern) in enumerate(definitions, start=1):
        match = re.search(pattern, section)
        if not match:
            raise ValueError(f"서울여대 {program} 집계행을 찾지 못했습니다.")
        quota, competition_rate, waitlist, best, average, worst = match.groups()
        metrics = [
            grade_metric("grade_final_best", "최종합격자 최고등급", best, "final_accepted"),
            grade_metric("grade_final_average", "최종합격자 평균등급", average, "final_accepted"),
            grade_metric("grade_final_worst", "최종합격자 최저등급", worst, "final_accepted"),
        ]
        output.append({
            "university": "서울여대", "track": "기회균형전형_특성화고교졸업자", "program": program,
            "page": 6, "table_index": 2, "row": row_index, "reported_year": 2026,
            "quota": number(quota), "competition_rate": number(competition_rate),
            "waitlist_rank": number(waitlist), "metrics": [metric for metric in metrics if metric],
            "raw": match.group(0),
        })
    return output


def seoul_theological_results(path: Path) -> list[dict]:
    """Read Seoul Theological's explicitly combined vocational-track summary."""
    with pdfplumber.open(path) as document:
        tables = document.pages[6].extract_tables()
    table = next((table for table in tables if len(table) == 6 and len(table[0]) == 6), None)
    if table is None:
        raise ValueError("서울신학대 특성화고졸업자 집계표를 찾지 못했습니다.")
    programs = [row[0].replace("\n", "") for row in table[2:] if row[0]]
    summary = table[2]
    metric = grade_metric("grade_average", "특성화고졸업자전형 학생부교과 평균성적", summary[4])
    if len(programs) != 4 or not metric:
        raise ValueError("서울신학대 4개 모집단위 집계 또는 평균등급을 읽지 못했습니다.")
    return [{
        "university": "서울신학대", "track": "특성화고졸업자전형",
        "program": " / ".join(programs) + " (4개 모집단위 집계)",
        "page": 7, "table_index": 2, "row": 2, "reported_year": 2026,
        "quota": number(summary[1]), "applicants": number(summary[2]),
        "competition_rate": number(summary[3]), "metrics": [metric], "raw": table[2:],
    }]


def ensure_institution(connection: sqlite3.Connection, university: str) -> int:
    row = connection.execute("SELECT id FROM institutions WHERE canonical_name = ?", (university,)).fetchone()
    if row:
        return row[0]
    source_rows = connection.execute("SELECT id FROM institutions WHERE source_name = ?", (university,)).fetchall()
    if len(source_rows) == 1:
        return source_rows[0][0]
    cursor = connection.execute(
        "INSERT INTO institutions(source_name, canonical_name, campus) VALUES (?, ?, ?)",
        (university, university, re.search(r"\(([^)]+)\)", university).group(1) if "(" in university else None),
    )
    return cursor.lastrowid


def merge_alias_institution(connection: sqlite3.Connection, alias: str, canonical_name: str) -> None:
    """Merge an earlier short-name institution into its canonical institution."""
    alias_row = connection.execute(
        "SELECT id FROM institutions WHERE source_name = ? AND canonical_name = ?",
        (alias, alias),
    ).fetchone()
    target_row = connection.execute(
        "SELECT id FROM institutions WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()
    if not alias_row or not target_row or alias_row[0] == target_row[0]:
        return
    alias_id, target_id = alias_row[0], target_row[0]
    connection.execute("UPDATE documents SET institution_id = ? WHERE institution_id = ?", (target_id, alias_id))
    for program_id, normalized_name in connection.execute(
        "SELECT id, normalized_name FROM programs WHERE institution_id = ?", (alias_id,)
    ).fetchall():
        existing = connection.execute(
            "SELECT id FROM programs WHERE institution_id = ? AND normalized_name = ?",
            (target_id, normalized_name),
        ).fetchone()
        if existing:
            connection.execute("UPDATE results SET program_id = ? WHERE program_id = ?", (existing[0], program_id))
            connection.execute("DELETE FROM programs WHERE id = ?", (program_id,))
        else:
            connection.execute("UPDATE programs SET institution_id = ? WHERE id = ?", (target_id, program_id))
    connection.execute("DELETE FROM institutions WHERE id = ?", (alias_id,))


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
    canonical_aliases = {
        "동명대": "동명대학교",
        "대진대": "대진대학교",
        "성결대": "성결대학교",
        "한신대": "한신대학교",
    }
    for alias, canonical_name in canonical_aliases.items():
        merge_alias_institution(connection, alias, canonical_name)
    nesin_imports = [
        (
            "동명대학교",
            NESIN_ROOT / "동명대" / "동명대학교" / "동명대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=189",
            tongmyong_results,
        ),
        (
            "대진대학교",
            NESIN_ROOT / "대진대" / "대진대학교" / "대진대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=51",
            daejin_results,
        ),
        (
            "성결대학교",
            NESIN_ROOT / "성결대" / "성결대학교" / "성결대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=55",
            sungkyul_results,
        ),
        (
            "한신대학교",
            NESIN_ROOT / "한신대" / "한신대학교" / "한신대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=77",
            hanshin_results,
        ),
        (
            "수원대학교",
            NESIN_ROOT / "수원대" / "수원대학교" / "수원대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=57",
            suwon_results,
        ),
        (
            "신한대학교(동두천)",
            NESIN_ROOT / "신한대" / "신한대학교(동두천)" / "신한대학교(동두천)__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=216",
            shinhan_results,
        ),
        (
            "광운대학교",
            NESIN_ROOT / "광운대" / "광운대학교" / "광운대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=7",
            kwangwoon_results,
        ),
        (
            "덕성여자대학교",
            NESIN_ROOT / "덕성여대" / "덕성여자대학교" / "덕성여자대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=11",
            duksung_results,
        ),
        (
            "서울여자대학교",
            NESIN_ROOT / "서울여대" / "서울여자대학교" / "서울여자대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=24",
            seoul_womens_results,
        ),
        (
            "서울신학대학교",
            NESIN_ROOT / "서울신학대" / "서울신학대학교" / "서울신학대학교__2026__입시결과.pdf",
            "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code=53",
            seoul_theological_results,
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
