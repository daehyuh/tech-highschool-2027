from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "입시결과_PDF"
PROFILE_PATH = ROOT / "data" / "pdf_profile.json"
INDEX_PATH = PDF_ROOT / "collection_index.csv"
DB_PATH = ROOT / "data" / "admissions.sqlite"
WEB_DATA_PATH = ROOT / "web" / "app" / "data" / "results.json"

TARGET_PATTERN = re.compile(r"특성화\s*고(?:교)?\s*(?:졸업자|출신자|동일계)|특성화고교졸업자|특성화고동일계|특성화고(?!등?을?졸업한재직자|졸재직자)")
WORKER_PATTERN = re.compile(r"특성화\s*고.*?재직자|특성화고졸재직자|특성화고등을졸업한재직자")
DEPARTMENT_SUFFIX = re.compile(r"(?:학과|학부|전공|계열|모집단위)$")
NUMBER_PATTERN = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE institutions (
  id INTEGER PRIMARY KEY,
  source_name TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  campus TEXT,
  UNIQUE(source_name, canonical_name)
);
CREATE TABLE documents (
  id INTEGER PRIMARY KEY,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  admission_year INTEGER NOT NULL,
  admission_cycle TEXT NOT NULL DEFAULT '수시',
  local_path TEXT NOT NULL UNIQUE,
  source_url TEXT,
  sha256 TEXT,
  page_count INTEGER
);
CREATE TABLE admission_tracks (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  name TEXT NOT NULL,
  normalized_category TEXT NOT NULL DEFAULT '특성화고교졸업자',
  is_vocational INTEGER NOT NULL DEFAULT 1,
  is_employed_worker INTEGER NOT NULL DEFAULT 0,
  UNIQUE(document_id, name)
);
CREATE TABLE programs (
  id INTEGER PRIMARY KEY,
  institution_id INTEGER NOT NULL REFERENCES institutions(id),
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  field_group TEXT NOT NULL,
  UNIQUE(institution_id, normalized_name)
);
CREATE TABLE results (
  id INTEGER PRIMARY KEY,
  track_id INTEGER NOT NULL REFERENCES admission_tracks(id),
  program_id INTEGER NOT NULL REFERENCES programs(id),
  page_number INTEGER NOT NULL,
  table_index INTEGER NOT NULL,
  row_index INTEGER NOT NULL,
  reported_year INTEGER,
  quota INTEGER,
  applicants INTEGER,
  competition_rate REAL,
  registrants INTEGER,
  waitlist_rank INTEGER,
  representative_grade REAL,
  representative_grade_basis TEXT,
  extraction_confidence REAL NOT NULL,
  raw_row_json TEXT NOT NULL,
  UNIQUE(track_id, program_id, page_number, table_index, row_index)
);
CREATE TABLE metrics (
  id INTEGER PRIMARY KEY,
  result_id INTEGER NOT NULL REFERENCES results(id) ON DELETE CASCADE,
  metric_code TEXT NOT NULL,
  source_label TEXT NOT NULL,
  value_numeric REAL,
  value_text TEXT,
  unit TEXT,
  cohort TEXT,
  percentile REAL,
  stage TEXT
);
CREATE TABLE raw_tables (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  page_number INTEGER NOT NULL,
  table_index INTEGER NOT NULL,
  extraction_strategy TEXT NOT NULL,
  rows_json TEXT NOT NULL
);
CREATE INDEX result_grade_idx ON results(representative_grade);
CREATE INDEX program_field_idx ON programs(field_group, normalized_name);
CREATE INDEX metric_code_value_idx ON metrics(metric_code, value_numeric);

CREATE VIEW counseling_results AS
SELECT r.id AS result_id,
       i.canonical_name AS university,
       i.campus,
       COALESCE(r.reported_year, d.admission_year) AS admission_year,
       d.admission_cycle,
       t.name AS admission_track,
       p.name AS program,
       p.field_group,
       r.quota,
       r.applicants,
       r.competition_rate,
       r.registrants,
       r.waitlist_rank,
       r.representative_grade,
       r.representative_grade_basis,
       r.extraction_confidence,
       d.local_path,
       d.source_url
FROM results r
JOIN admission_tracks t ON t.id = r.track_id
JOIN documents d ON d.id = t.document_id
JOIN institutions i ON i.id = d.institution_id
JOIN programs p ON p.id = r.program_id
WHERE t.is_vocational = 1 AND t.is_employed_worker = 0;

CREATE VIEW latest_counseling_results AS
SELECT * FROM (
  SELECT cr.*,
         ROW_NUMBER() OVER (
           PARTITION BY cr.university, cr.program
           ORDER BY cr.admission_year DESC, cr.extraction_confidence DESC, cr.result_id DESC
         ) AS recency_rank
  FROM counseling_results cr
)
WHERE recency_rank = 1;
"""


def clean(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def numeric(value: str) -> float | None:
    match = NUMBER_PATTERN.search(value.replace(",", ""))
    return float(match.group()) if match else None


def integer(value: str) -> int | None:
    parsed = numeric(value)
    return int(parsed) if parsed is not None and parsed.is_integer() else None


def normalize_program(value: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value).lower()


def valid_program(value: str) -> bool:
    name = clean(value)
    if name in {"학과", "학부", "전공", "계열", "공학과", "공학부"}:
        return False
    if re.search(r"전형|제외한\s*모든|등급\s*점수", name):
        return False
    if re.match(r"^(?:도AI|도운전|도전기|도차량|노화학|영학과|학공학|학부경영|학생부)", name):
        return False
    return len(normalize_program(name)) >= 3


def field_group(name: str) -> str:
    rules = [
        ("컴퓨터·AI", r"컴퓨터|소프트웨어|인공지능|AI|데이터|정보보호|게임"),
        ("전기·전자", r"전기|전자|반도체|정보통신"),
        ("기계·자동차", r"기계|자동차|로봇|모빌리티|항공|조선"),
        ("건축·토목", r"건축|토목|건설|도시|환경공학|인프라"),
        ("화학·소재", r"화학|화공|재료|신소재|나노"),
        ("생명·식품", r"생명|바이오|식품|동물|축산|산림|자원"),
        ("보건·의료", r"간호|의예|치의|약학|보건|의료|물리치료|응급"),
        ("경영·경제", r"경영|경제|무역|금융|회계|세무|물류|부동산"),
        ("사회·행정", r"행정|정치|사회|복지|법학|경찰"),
        ("인문·교육", r"국어|영어|문학|역사|철학|교육|언어"),
        ("예체능", r"디자인|미술|체육|음악|연극|영화|콘텐츠"),
    ]
    for label, pattern in rules:
        if re.search(pattern, name, re.I):
            return label
    return "기타"


def extract_track(text: str) -> str | None:
    lines = [clean(line) for line in text.splitlines()]
    for line in lines:
        if TARGET_PATTERN.search(line) and not WORKER_PATTERN.search(line):
            match = re.search(r"[^\[▷□▢※]{0,30}특성화[^\]\n]{0,40}(?:전형|졸업자|동일계)", line)
            return clean(match.group())[:100] if match else clean(line)[:100]
    return None


def department_from_cells(cells: list[str]) -> tuple[str | None, int | None]:
    candidates: list[tuple[str, int]] = []
    for index, cell in enumerate(cells):
        prefix = re.split(r"(?=\s-?\d)|(?<=과)(?=-?\d)|(?<=부)(?=-?\d)", cell, maxsplit=1)[0].strip(" ·-")
        if DEPARTMENT_SUFFIX.search(prefix) and not re.search(r"단과대학|모집단위|특성화|전형", prefix):
            if (
                index > 0
                and cells[index - 1]
                and not NUMBER_PATTERN.search(cells[index - 1])
                and not re.search(r"특성화|학교장|전형|교과|종합", cells[index - 1])
                and not cells[index - 1].endswith("대학")
                and len(cells[index - 1]) <= 14
            ):
                prefix = clean(cells[index - 1] + prefix)
            candidates.append((prefix, index))
    if candidates:
        return candidates[-1]
    if len(cells) >= 2:
        joined = clean(f"{cells[0]} {cells[1]}")
        prefix = re.split(r"(?=\s-?\d)", joined, maxsplit=1)[0].strip(" ·-")
        if DEPARTMENT_SUFFIX.search(prefix) and not re.search(r"모집단위|특성화|전형", prefix):
            return prefix, 1
    return None, None


def metric_code(label: str, grade_context: bool = False) -> tuple[str, str | None, float | None, str | None]:
    compact = re.sub(r"\s+", "", label).lower()
    if "경쟁" in compact:
        return "competition_rate", "ratio", None, None
    if "지원" in compact:
        return "applicants", "people", None, None
    if "모집" in compact and "단위" not in compact:
        return "quota", "people", None, None
    if "등록자" in compact and "등급" not in compact:
        return "registrants", "people", None, None
    if "충원" in compact or "예비" in compact:
        return "waitlist_rank", "rank", None, None
    if "70" in compact and ("등급" in compact or "cut" in compact or "컷" in compact):
        return "grade_70_cut", "grade", 70.0, "final_registered"
    if "50" in compact and ("등급" in compact or "cut" in compact or "컷" in compact):
        return "grade_50_cut", "grade", 50.0, "final_registered"
    if grade_context or "등급" in compact or "내신" in compact or "학생부" in compact:
        stage = "final_registered" if "최종" in compact or "등록" in compact else "initial" if "최초" in compact or "합격" in compact else None
        if "최종" in compact and "평균" in compact:
            return "grade_final_average", "grade", None, "final_registered"
        if "평균" in compact:
            return ("grade_final_average" if stage == "final_registered" else "grade_initial_average" if stage == "initial" else "grade_average"), "grade", None, stage
        if "최고" in compact:
            return ("grade_final_best" if stage == "final_registered" else "grade_initial_best" if stage == "initial" else "grade_best"), "grade", None, stage
        if "최저" in compact:
            return ("grade_final_worst" if stage == "final_registered" else "grade_initial_worst" if stage == "initial" else "grade_worst"), "grade", None, stage
    if "총점" in compact or "환산점수" in compact:
        return "converted_score", "score", None, None
    return "raw_metric", None, None, None


@dataclass
class ParsedResult:
    track: str
    program: str
    page: int
    table_index: int
    row_index: int
    raw: list[str]
    metrics: list[dict]
    confidence: float
    reported_year: int | None = None


def special_korea_transport(rows: list[list[str]], page_text: str, page_no: int, table_index: int) -> list[ParsedResult]:
    if "특성화고동일계전형" not in re.sub(r"\s+", "", page_text):
        return []
    output = []
    for row_index, cells in enumerate(rows):
        cells = [clean(cell) for cell in cells]
        program, _ = department_from_cells(cells)
        if not program or program == "합계":
            continue
        _, program_col = department_from_cells(cells)
        values = [NUMBER_PATTERN.findall(cell.replace(",", "")) for cell in cells]
        base = program_col if program_col is not None else 0
        if len(cells) < base + 11 or not values[base + 2] or not values[base + 3]:
            continue
        metrics = []
        def add(code: str, label: str, value: str | None, unit: str, stage: str | None = None):
            if value not in (None, ""):
                metrics.append({"code": code, "label": label, "value": float(value), "unit": unit, "stage": stage})
        add("converted_score", "최종등록자 총점평균", values[base + 1][0] if values[base + 1] else None, "score")
        add("quota", "모집인원", values[base + 2][0] if values[base + 2] else None, "people")
        add("applicants", "지원인원", values[base + 3][0] if values[base + 3] else None, "people")
        add("competition_rate", "경쟁률", values[base + 4][0] if values[base + 4] else None, "ratio")
        add("registrants", "등록자", values[base + 5][0] if values[base + 5] else None, "people")
        packed = values[base + 6]
        add("waitlist_rank", "예비순위", packed[0] if packed else None, "rank")
        add("grade_initial_best", "최초합격자 최고", packed[1] if len(packed) > 1 else None, "grade", "initial")
        add("grade_initial_average", "최초합격자 평균", packed[2] if len(packed) > 2 else None, "grade", "initial")
        add("grade_initial_worst", "최초합격자 최저", values[base + 7][0] if values[base + 7] else None, "grade", "initial")
        add("grade_final_best", "최종등록자 최고", values[base + 8][0] if values[base + 8] else None, "grade", "final_registered")
        add("grade_final_average", "최종등록자 평균", values[base + 9][0] if values[base + 9] else None, "grade", "final_registered")
        add("grade_final_worst", "최종등록자 최저", values[base + 10][0] if len(values) > base + 10 and values[base + 10] else None, "grade", "final_registered")
        output.append(ParsedResult("특성화고동일계전형", program, page_no, table_index, row_index, cells, metrics, 0.98))
    return output


def special_seokyeong(rows: list[list[str]], page_no: int, table_index: int) -> list[ParsedResult]:
    output: list[ParsedResult] = []
    for row_index, raw in enumerate(rows):
        cells = [clean(cell) if "\n" not in str(cell or "") else str(cell or "").strip() for cell in raw]
        if len(cells) < 5 or not re.search(r"특성화\s*고교\s*졸업자", cells[0].replace("\n", "")):
            continue
        raw_programs = [clean(value) for value in cells[1].splitlines() if clean(value)]
        programs: list[str] = []
        pending = ""
        for value in raw_programs:
            pending = clean(pending + value)
            if DEPARTMENT_SUFFIX.search(re.sub(r"\d+$", "", pending)):
                programs.append(pending)
                pending = ""
        if pending:
            programs.append(pending)
        stat_lines = [clean(value) for value in cells[2].splitlines() if clean(value)]
        wait_lines = [clean(value) for value in cells[3].splitlines() if clean(value)]
        grade50_lines = [clean(value) for value in cells[4].splitlines() if clean(value)]
        for offset, program in enumerate(programs):
            source = [clean(cell) for cell in (rows[row_index + offset] if row_index + offset < len(rows) else raw)]
            metrics: list[dict] = []
            stat_values = NUMBER_PATTERN.findall(stat_lines[offset].replace(",", "")) if offset < len(stat_lines) else []
            grade50_values = NUMBER_PATTERN.findall(grade50_lines[offset]) if offset < len(grade50_lines) else []
            continuation = rows[row_index + offset] if row_index + offset < len(rows) else []

            def add(code: str, label: str, value: str | None, unit: str, percentile: float | None = None):
                if value not in (None, "", "-"):
                    metrics.append({"code": code, "label": label, "value": float(value), "unit": unit, "percentile": percentile, "stage": "final_registered" if code.startswith("grade_") else None})

            add("quota", "모집인원", stat_values[0] if len(stat_values) > 0 else None, "people")
            add("applicants", "지원인원", stat_values[1] if len(stat_values) > 1 else None, "people")
            add("competition_rate", "지원비율", stat_values[2] if len(stat_values) > 2 else None, "ratio")
            wait_values = NUMBER_PATTERN.findall(wait_lines[offset]) if offset < len(wait_lines) else []
            add("waitlist_rank", "최종예비번호", wait_values[0] if wait_values else None, "rank")
            add("grade_50_cut", "학생부교과 50% Cut 등급", grade50_values[-1] if len(grade50_values) >= 2 else None, "grade", 50.0)
            add("grade_70_cut", "학생부교과 70% Cut 등급", numeric(clean(continuation[6])) if len(continuation) > 6 else None, "grade", 70.0)
            add("grade_worst", "학생부교과 100% Cut 등급", numeric(clean(continuation[8])) if len(continuation) > 8 else None, "grade", 100.0)
            if metrics:
                output.append(ParsedResult("특성화고교졸업자", program, page_no, table_index, row_index + offset, source, metrics, 0.97))
    return output


def special_kongju(rows: list[list[str]], page_no: int, table_index: int) -> list[ParsedResult]:
    output: list[ParsedResult] = []
    for row_index, raw in enumerate(rows):
        cells = [clean(cell) for cell in raw]
        if len(cells) < 15 or cells[0] != "실기_특성화고":
            continue
        program = cells[2]
        if not DEPARTMENT_SUFFIX.search(program) or not re.fullmatch(r"20\d{2}", cells[3]):
            continue
        metrics: list[dict] = []

        def add(code: str, label: str, value: float | None, unit: str, percentile: float | None = None):
            if value is not None:
                metrics.append({"code": code, "label": label, "value": value, "unit": unit, "percentile": percentile, "stage": "final_registered" if code.startswith("grade_") else None})

        add("quota", "모집인원", numeric(cells[4]), "people")
        add("competition_rate", "경쟁률", numeric(cells[5]), "ratio")
        add("registrants", "최종등록인원", numeric(cells[9]), "people")
        add("waitlist_rank", "추가합격인원", numeric(cells[10]), "rank")
        add("grade_initial_average", "최초합격자 학생부등급 50%", numeric(cells[11]), "grade", 50.0)
        add("grade_initial_worst", "최초합격자 학생부등급 70%", numeric(cells[12]), "grade", 70.0)
        add("grade_50_cut", "최종등록자 학생부등급 50%", numeric(cells[13]), "grade", 50.0)
        add("grade_70_cut", "최종등록자 학생부등급 70%", numeric(cells[14]), "grade", 70.0)
        output.append(ParsedResult("실기_특성화고", program, page_no, table_index, row_index, cells, metrics, 0.88, int(cells[3])))
    return output


def special_sungkyunkwan(rows: list[list[str]], page_no: int, table_index: int) -> list[ParsedResult]:
    """The university publishes one aggregate result for seven eligible programs."""
    output: list[ParsedResult] = []
    for row_index, raw in enumerate(rows):
        cells = [clean(cell) for cell in raw]
        programs = [clean(value) for value in ((raw[1] or "").splitlines() if len(raw) > 1 else []) if clean(value)]
        if len(cells) < 6 or len(programs) != 7 or programs[-1] != "소프트웨어학과":
            continue
        if numeric(cells[2]) != 25 or numeric(cells[3]) != 581:
            continue
        metrics = [
            {"code": "quota", "label": "모집인원(7개 모집단위 통합)", "value": 25.0, "unit": "people", "percentile": None, "stage": None},
            {"code": "applicants", "label": "지원인원(7개 모집단위 통합)", "value": 581.0, "unit": "people", "percentile": None, "stage": None},
            {"code": "competition_rate", "label": "경쟁률(7개 모집단위 통합)", "value": 23.24, "unit": "ratio", "percentile": None, "stage": None},
            {"code": "waitlist_rank", "label": "충원합격인원(7개 모집단위 통합)", "value": 6.0, "unit": "people", "percentile": None, "stage": None},
        ]
        output.append(ParsedResult(
            "특성화고", "인문과학계열 외 6개 모집단위(통합)", page_no, table_index,
            row_index, cells, metrics, 0.99, 2025,
        ))
    return output


def parse_generic(rows: list[list[str]], page_text: str, page_no: int, table_index: int) -> list[ParsedResult]:
    output: list[ParsedResult] = []
    current_track = extract_track(page_text) or "특성화고교졸업자전형"
    header_rows: list[list[str]] = []
    seen_header = False
    max_cols = max((len(row) for row in rows), default=0)
    compact_page = re.sub(r"\s+", "", page_text)
    grade_context = bool(
        re.search(r"(?:학생부|교과|내신).{0,20}(?:성적|등급)|(?:성적|등급).{0,20}(?:통계|현황|평균)", compact_page)
    )
    table_has_track_column = any(
        "모집전형" in re.sub(r"\s+", "", " ".join(clean(cell) for cell in row))
        or "전형구분" in re.sub(r"\s+", "", " ".join(clean(cell) for cell in row))
        for row in rows[:8]
    )
    current_program: str | None = None
    current_program_col: int | None = None
    for row_index, raw_row in enumerate(rows):
        cells = [clean(cell) for cell in raw_row] + [""] * (max_cols - len(raw_row))
        joined = clean(" ".join(cells))
        compact = re.sub(r"\s+", "", joined)
        if not table_has_track_column and TARGET_PATTERN.search(compact) and ("전형" in compact or "졸업자" in compact or "동일계" in compact):
            if not WORKER_PATTERN.search(compact):
                current_track = joined[:100]
            else:
                current_track = "특성화고졸재직자"
            header_rows = []
            seen_header = False
            continue
        if "모집단위" in compact or "모집학과" in compact or "학과명" in compact:
            seen_header = True
            header_rows = [cells]
            continue
        program, program_col = department_from_cells(cells)
        if program:
            current_program = program
            current_program_col = program_col
        elif table_has_track_column and TARGET_PATTERN.search(compact) and current_program:
            program = current_program
            program_col = current_program_col
        if not program:
            if seen_header and any(term in compact for term in ("평균", "최고", "최저", "50%", "70%", "등급", "경쟁률")):
                header_rows.append(cells)
            continue
        if WORKER_PATTERN.search(current_track):
            continue
        if table_has_track_column:
            if WORKER_PATTERN.search(compact) or not TARGET_PATTERN.search(compact):
                continue
            current_track = next((cell for cell in cells if TARGET_PATTERN.search(re.sub(r"\s+", "", cell))), current_track)
        col_labels = []
        for col in range(max_cols):
            label = clean(" ".join(row[col] for row in header_rows if col < len(row) and row[col]))
            col_labels.append(label or f"열{col + 1}")
        metrics: list[dict] = []
        for col, cell in enumerate(cells):
            if col == program_col:
                cell = cell[len(program):].strip()
            numbers = NUMBER_PATTERN.findall(cell.replace(",", ""))
            for token_index, token in enumerate(numbers):
                label = col_labels[col] + (f" 값{token_index + 1}" if len(numbers) > 1 else "")
                code, unit, percentile, stage = metric_code(label, grade_context=grade_context)
                metrics.append({"code": code, "label": label, "value": float(token), "unit": unit, "percentile": percentile, "stage": stage})
        if metrics:
            confidence = 0.78 if seen_header else 0.55
            year_match = next((re.fullmatch(r"20\d{2}", cell) for cell in cells if re.fullmatch(r"20\d{2}", cell)), None)
            reported_year = int(year_match.group()) if year_match else None
            output.append(ParsedResult(current_track, program, page_no, table_index, row_index, cells, metrics, confidence, reported_year))
    return output


def extract_text_tables(page) -> list[list[list[str]]]:
    settings = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "intersection_tolerance": 8,
        "snap_tolerance": 5,
    }
    return page.extract_tables(settings) or []


def choose_tables(page) -> list[list[list[str]]]:
    line_tables = page.extract_tables(
        {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    ) or []
    if any(
        any(term in clean(" ".join(clean(cell) for cell in row)) for term in ("모집전형", "전형구분", "전형명", "전형"))
        and any(term in clean(" ".join(clean(cell) for cell in row)) for term in ("모집단위", "모집단위명", "모집학과"))
        for table in line_tables
        for row in (table or [])[:8]
    ):
        return line_tables
    text_tables = extract_text_tables(page)
    text_program_rows = sum(
        bool(DEPARTMENT_SUFFIX.search(clean(cell)))
        for table in text_tables
        for row in table or []
        for cell in row or []
    )
    if text_program_rows:
        return text_tables
    return page.extract_tables(
        {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    ) or text_tables


def main() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile_by_path = {row["path"].replace("\\", "/"): row for row in profile["documents"]}
    index_rows = list(csv.DictReader(INDEX_PATH.open(encoding="utf-8-sig")))
    document_meta = {row["local_path"].replace("\\", "/"): row for row in index_rows if row["status"] == "downloaded"}

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    connection = sqlite3.connect(DB_PATH)
    connection.executescript(SCHEMA)

    institution_ids: dict[tuple[str, str], int] = {}
    document_ids: dict[str, int] = {}
    extracted: list[ParsedResult] = []

    for relative_path, profile_row in profile_by_path.items():
        if not profile_row["keyword_pages"]:
            continue
        meta = document_meta.get(relative_path)
        if not meta:
            continue
        path = ROOT / Path(relative_path)
        source_name = meta["source_name"]
        canonical_name = meta["site_name"]
        key = (source_name, canonical_name)
        if key not in institution_ids:
            cursor = connection.execute(
                "INSERT INTO institutions(source_name, canonical_name, campus) VALUES (?, ?, ?)",
                (source_name, canonical_name, re.search(r"\(([^)]+)\)", canonical_name).group(1) if "(" in canonical_name else None),
            )
            institution_ids[key] = cursor.lastrowid
        year_match = re.search(r"__(\d{4})__", path.name)
        admission_year = int(year_match.group(1)) if year_match else 0
        cursor = connection.execute(
            "INSERT INTO documents(institution_id, admission_year, local_path, source_url, sha256, page_count) VALUES (?, ?, ?, ?, ?, ?)",
            (institution_ids[key], admission_year, relative_path, meta["source_url"], meta["sha256"], profile_row["pages"]),
        )
        document_id = cursor.lastrowid
        document_ids[relative_path] = document_id
        candidate_pages = {row["page"] for row in profile_row["keyword_pages"]}
        try:
            with pdfplumber.open(path) as pdf:
                for page_no in sorted(candidate_pages):
                    page = pdf.pages[page_no - 1]
                    page_text = page.extract_text() or ""
                    compact_text = re.sub(r"\s+", "", page_text)
                    tables = extract_text_tables(page) if "한국교통대학교" in canonical_name else choose_tables(page)
                    table_text = re.sub(r"\s+", "", " ".join(clean(cell) for table in tables for row in (table or []) for cell in (row or [])))
                    if not TARGET_PATTERN.search(compact_text) and not TARGET_PATTERN.search(table_text):
                        continue
                    for table_index, table in enumerate(tables):
                        raw_rows = [row for row in table if row]
                        rows = [[clean(cell) for cell in row] for row in raw_rows]
                        if not rows:
                            continue
                        connection.execute(
                            "INSERT INTO raw_tables(document_id, page_number, table_index, extraction_strategy, rows_json) VALUES (?, ?, ?, ?, ?)",
                            (document_id, page_no, table_index, "pdfplumber_text", json.dumps(rows, ensure_ascii=False)),
                        )
                        parsed = []
                        if "한국교통대학교" in canonical_name:
                            parsed = special_korea_transport(rows, page_text, page_no, table_index)
                        elif "서경대학교" in canonical_name:
                            parsed = special_seokyeong(raw_rows, page_no, table_index)
                        elif "국립공주대학교" in canonical_name:
                            parsed = special_kongju(rows, page_no, table_index)
                        elif "성균관대학교" in canonical_name:
                            parsed = special_sungkyunkwan(raw_rows, page_no, table_index)
                        if not parsed:
                            parsed = parse_generic(rows, page_text, page_no, table_index)
                        extracted.extend((relative_path, item) for item in parsed)
        except Exception as exc:
            print(f"WARN {relative_path}: {type(exc).__name__}: {exc}")

    program_ids: dict[tuple[int, str], int] = {}
    track_ids: dict[tuple[int, str], int] = {}
    export_rows = []
    for relative_path, item in extracted:
        document_id = document_ids[relative_path]
        institution_id = connection.execute("SELECT institution_id FROM documents WHERE id = ?", (document_id,)).fetchone()[0]
        track_key = (document_id, item.track)
        if track_key not in track_ids:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO admission_tracks(document_id, name, is_employed_worker) VALUES (?, ?, 0)",
                (document_id, item.track),
            )
            track_ids[track_key] = cursor.lastrowid or connection.execute(
                "SELECT id FROM admission_tracks WHERE document_id = ? AND name = ?", track_key
            ).fetchone()[0]
        if not valid_program(item.program):
            continue
        normalized = normalize_program(item.program)
        program_key = (institution_id, normalized)
        if not normalized:
            continue
        if program_key not in program_ids:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO programs(institution_id, name, normalized_name, field_group) VALUES (?, ?, ?, ?)",
                (institution_id, item.program, normalized, field_group(item.program)),
            )
            program_ids[program_key] = cursor.lastrowid or connection.execute(
                "SELECT id FROM programs WHERE institution_id = ? AND normalized_name = ?", program_key
            ).fetchone()[0]
        metric_map: dict[str, float] = {}
        for metric in item.metrics:
            code = metric["code"]
            value = metric["value"]
            if code == "raw_metric":
                continue
            if code.startswith("grade_") and 0.5 <= value <= 9.5:
                metric_map[code] = value
            elif code not in metric_map:
                metric_map[code] = value
        grade_priority = ["grade_70_cut", "grade_final_average", "grade_average", "grade_50_cut", "grade_final_worst", "grade_initial_average"]
        representative_code = next((code for code in grade_priority if code in metric_map and 0.5 <= metric_map[code] <= 9.5), None)
        representative_grade = metric_map.get(representative_code) if representative_code else None
        cursor = connection.execute(
            """INSERT OR IGNORE INTO results(
              track_id, program_id, page_number, table_index, row_index, reported_year, quota, applicants, competition_rate,
              registrants, waitlist_rank, representative_grade, representative_grade_basis, extraction_confidence, raw_row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (track_ids[track_key], program_ids[program_key], item.page, item.table_index, item.row_index, item.reported_year,
             int(metric_map["quota"]) if "quota" in metric_map else None,
             int(metric_map["applicants"]) if "applicants" in metric_map else None,
             metric_map.get("competition_rate"), int(metric_map["registrants"]) if "registrants" in metric_map else None,
             int(metric_map["waitlist_rank"]) if "waitlist_rank" in metric_map else None,
             representative_grade, representative_code, item.confidence, json.dumps(item.raw, ensure_ascii=False)),
        )
        result_id = cursor.lastrowid
        if not result_id:
            continue
        for metric in item.metrics:
            connection.execute(
                "INSERT INTO metrics(result_id, metric_code, source_label, value_numeric, unit, cohort, percentile, stage) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (result_id, metric["code"], metric["label"], metric["value"], metric.get("unit"), None, metric.get("percentile"), metric.get("stage")),
            )

    connection.commit()
    query = """
      SELECT r.id, i.source_name, i.canonical_name, COALESCE(r.reported_year, d.admission_year) AS admission_year, t.name AS track_name,
             p.name AS program_name, p.field_group, r.quota, r.applicants, r.competition_rate,
             r.registrants, r.waitlist_rank, r.representative_grade, r.representative_grade_basis,
             r.extraction_confidence, r.page_number, d.local_path, d.source_url
      FROM results r
      JOIN admission_tracks t ON t.id = r.track_id
      JOIN documents d ON d.id = t.document_id
      JOIN institutions i ON i.id = d.institution_id
      JOIN programs p ON p.id = r.program_id
      WHERE t.is_employed_worker = 0
      ORDER BY d.admission_year DESC, i.source_name, p.name
    """
    columns = [description[0] for description in connection.execute(query).description]
    for row in connection.execute(query):
        export_rows.append(dict(zip(columns, row)))
    metrics_by_result: dict[int, list[dict]] = {}
    for row in connection.execute("SELECT result_id, metric_code, source_label, value_numeric, unit, percentile, stage FROM metrics ORDER BY id"):
        metrics_by_result.setdefault(row[0], []).append({
            "code": row[1], "label": row[2], "value": row[3], "unit": row[4], "percentile": row[5], "stage": row[6]
        })
    for row in export_rows:
        row["metrics"] = metrics_by_result.get(row["id"], [])
    payload = {
        "generated_from": "2027_특성화고_모집대학.xlsm 및 수집 입시결과 PDF",
        "summary": {
            "result_count": len(export_rows),
            "institution_count": len({row["canonical_name"] for row in export_rows}),
            "program_count": len({(row["canonical_name"], row["program_name"]) for row in export_rows}),
            "grade_result_count": sum(row["representative_grade"] is not None for row in export_rows),
        },
        "results": export_rows,
    }
    WEB_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    connection.close()


if __name__ == "__main__":
    main()
