from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "입시결과_PDF"
PROFILE_PATH = ROOT / "data" / "pdf_profile.json"
INDEX_PATH = PDF_ROOT / "collection_index.csv"
DB_PATH = ROOT / "data" / "admissions.sqlite"
REPORT_JSON = ROOT / "data" / "coverage_report.json"
REPORT_CSV = ROOT / "data" / "coverage_by_university.csv"
WEB_COVERAGE_PATH = ROOT / "web" / "app" / "data" / "coverage.json"


def main() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    candidate_paths = {
        row["path"].replace("\\", "/")
        for row in profile["documents"]
        if row["keyword_pages"]
    }
    candidate_page_details = {
        row["path"].replace("\\", "/"): row["keyword_pages"]
        for row in profile["documents"]
        if row["keyword_pages"]
    }
    index_rows = list(csv.DictReader(INDEX_PATH.open(encoding="utf-8-sig")))
    downloaded = [row for row in index_rows if row["status"] == "downloaded"]

    source_by_path = {
        row["local_path"].replace("\\", "/"): row for row in downloaded
    }
    discovered = sorted({row["site_name"] for row in downloaded})
    candidate_universities = sorted(
        {
            source_by_path[path]["site_name"]
            for path in candidate_paths
            if path in source_by_path
        }
    )

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT i.canonical_name, d.local_path,
               COUNT(DISTINCT r.id) AS result_count,
               COUNT(DISTINCT CASE WHEN r.representative_grade IS NOT NULL THEN r.id END) AS grade_count,
               COUNT(DISTINCT rt.id) AS raw_table_count,
               COUNT(DISTINCT p.id) AS program_count,
               MIN(r.extraction_confidence) AS minimum_confidence
        FROM documents d
        JOIN institutions i ON i.id = d.institution_id
        LEFT JOIN admission_tracks t ON t.document_id = d.id
        LEFT JOIN results r ON r.track_id = t.id
        LEFT JOIN programs p ON p.id = r.program_id
        LEFT JOIN raw_tables rt ON rt.document_id = d.id
        GROUP BY i.canonical_name, d.local_path
        """
    ).fetchall()

    by_university: dict[str, dict] = defaultdict(
        lambda: {
            "documents": 0,
            "candidate_documents": 0,
            "raw_tables": 0,
            "results": 0,
            "programs": 0,
            "grade_results": 0,
            "minimum_confidence": None,
        }
    )
    for row in rows:
        item = by_university[row["canonical_name"]]
        item["documents"] += 1
        item["candidate_documents"] += int(row["local_path"].replace("\\", "/") in candidate_paths)
        item["raw_tables"] += row["raw_table_count"]
        item["results"] += row["result_count"]
        item["programs"] += row["program_count"]
        item["grade_results"] += row["grade_count"]
        confidence = row["minimum_confidence"]
        if confidence is not None:
            item["minimum_confidence"] = (
                confidence
                if item["minimum_confidence"] is None
                else min(confidence, item["minimum_confidence"])
            )

    suspicious_rows = connection.execute(
        """
        SELECT i.canonical_name, p.name, COUNT(*) AS result_count
        FROM results r
        JOIN programs p ON p.id = r.program_id
        JOIN admission_tracks t ON t.id = r.track_id
        JOIN documents d ON d.id = t.document_id
        JOIN institutions i ON i.id = d.institution_id
        GROUP BY i.canonical_name, p.name
        """
    ).fetchall()
    suspicious_programs = []
    fragment_start = re.compile(r"^(?:도AI|도운전|도전기|도차량|노화학|영학과|학공학|학부경영|학생부)")
    for row in suspicious_rows:
        name = row["name"].strip()
        if (
            name in {"학과", "학부", "전공", "계열", "공학과", "공학부"}
            or fragment_start.search(name)
            or "전형" in name
            or "제외한모든" in name
        ):
            suspicious_programs.append(dict(row))

    coverage_rows = []
    for university in discovered:
        item = dict(by_university.get(university, {}))
        if not item:
            item = {
                "documents": 0,
                "candidate_documents": 0,
                "raw_tables": 0,
                "results": 0,
                "programs": 0,
                "grade_results": 0,
                "minimum_confidence": None,
            }
        item["university"] = university
        item["candidate_pages"] = [
            {
                "path": path,
                "pages": [page["page"] for page in candidate_page_details[path]],
                "snippets": [page["snippet"] for page in candidate_page_details[path]],
            }
            for path, meta in source_by_path.items()
            if meta["site_name"] == university and path in candidate_page_details
        ]
        item["status"] = (
            "grade_available"
            if item["grade_results"]
            else "results_without_grade"
            if item["results"]
            else "candidate_not_extracted"
            if university in candidate_universities
            else "no_candidate_pdf"
        )
        coverage_rows.append(item)

    summary = {
        "downloaded_universities": len(discovered),
        "candidate_universities": len(candidate_universities),
        "universities_with_results": sum(row["results"] > 0 for row in coverage_rows),
        "universities_with_grade_results": sum(row["grade_results"] > 0 for row in coverage_rows),
        "candidate_universities_without_results": sum(
            row["status"] == "candidate_not_extracted" for row in coverage_rows
        ),
        "universities_without_candidate_pdf": sum(
            row["status"] == "no_candidate_pdf" for row in coverage_rows
        ),
        "suspicious_program_count": len(suspicious_programs),
    }
    report = {
        "summary": summary,
        "universities": coverage_rows,
        "suspicious_programs": suspicious_programs,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    WEB_COVERAGE_PATH.write_text(
        json.dumps({"target_universities": 82, **summary}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    fieldnames = [
        "university",
        "status",
        "documents",
        "candidate_documents",
        "raw_tables",
        "results",
        "programs",
        "grade_results",
        "minimum_confidence",
    ]
    with REPORT_CSV.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fieldnames} for row in coverage_rows)
    print(json.dumps(summary, ensure_ascii=False))
    connection.close()


if __name__ == "__main__":
    main()
