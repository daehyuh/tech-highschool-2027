from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "입시결과_PDF"
TARGETS_PATH = ROOT / "data" / "target_universities.json"
PROFILE_PATH = ROOT / "data" / "pdf_profile.json"
INDEX_PATH = PDF_ROOT / "collection_index.csv"
DB_PATH = ROOT / "data" / "admissions.sqlite"
ADIGA_PATH = ROOT / "data" / "adiga_sources.json"
JSON_PATH = ROOT / "data" / "target_coverage.json"
CSV_PATH = ROOT / "data" / "target_coverage.csv"
WEB_PATH = ROOT / "web" / "app" / "data" / "target_coverage.json"


def main() -> None:
    targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))["targets"]
    adiga_sources = {
        row["university"]: row
        for row in json.loads(ADIGA_PATH.read_text(encoding="utf-8"))["sources"]
    } if ADIGA_PATH.exists() else {}
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    candidate_paths = {
        item["path"].replace("\\", "/")
        for item in profile["documents"]
        if item["keyword_pages"]
    }
    index_rows = list(csv.DictReader(INDEX_PATH.open(encoding="utf-8-sig")))
    downloaded_by_source: dict[str, list[dict]] = defaultdict(list)
    for row in index_rows:
        if row["status"] == "downloaded":
            downloaded_by_source[row["source_name"]].append(row)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    output = []
    for target in targets:
        name = target["university"]
        documents = downloaded_by_source.get(name, [])
        adiga = adiga_sources.get(name)
        stats = dict(connection.execute(
            """
            SELECT COUNT(DISTINCT r.id) AS result_count,
                   COUNT(DISTINCT p.id) AS program_count,
                   COUNT(DISTINCT CASE WHEN r.representative_grade IS NOT NULL THEN r.id END) AS grade_result_count,
                   COUNT(DISTINCT CASE WHEN r.extraction_confidence >= 0.75 THEN r.id END) AS high_confidence_count
            FROM institutions i LEFT JOIN documents d ON d.institution_id=i.id
            LEFT JOIN admission_tracks t ON t.document_id=d.id LEFT JOIN results r ON r.track_id=t.id
            LEFT JOIN programs p ON p.id=r.program_id
            WHERE i.source_name=? OR i.canonical_name=?
            """, (name, name)
        ).fetchone())
        database_documents = [dict(row) for row in connection.execute(
            """SELECT DISTINCT d.admission_year AS year, d.local_path, d.source_url
               FROM institutions i JOIN documents d ON d.institution_id=i.id
               WHERE i.source_name=? OR i.canonical_name=? ORDER BY d.admission_year DESC""",
            (name, name),
        )]
        source_paths = {row["local_path"] for row in database_documents}
        if adiga and adiga.get("status") == "downloaded":
            source_paths.add(adiga["local_path"])
        candidate_documents = [
            row for row in documents if row["local_path"].replace("\\", "/") in candidate_paths
        ]
        result_count = int(stats.get("result_count") or 0)
        grade_count = int(stats.get("grade_result_count") or 0)
        if grade_count:
            status = "grade_available"
        elif result_count:
            status = "results_without_grade"
        elif adiga and adiga.get("status") == "downloaded":
            status = "source_checked_no_result"
        elif candidate_documents:
            status = "candidate_not_extracted"
        elif documents:
            status = "pdf_without_target_result"
        else:
            status = "not_on_nesin"
        output.append(
            {
                "university": name,
                "cycles": target["cycles"],
                "regions": target["regions"],
                "status": status,
                "pdf_count": len(documents),
                "candidate_pdf_count": len(candidate_documents),
                "result_count": result_count,
                "program_count": int(stats.get("program_count") or 0),
                "grade_result_count": grade_count,
                "high_confidence_count": int(stats.get("high_confidence_count") or 0),
                "source_count": len(source_paths),
                "documents": [
                    {
                        "site_name": row["site_name"],
                        "year": int(row["year"]),
                        "local_path": row["local_path"],
                        "source_url": row["source_url"],
                        "is_candidate": row["local_path"].replace("\\", "/") in candidate_paths,
                    }
                    for row in documents
                ] + [
                    {
                        "site_name": name,
                        "year": int(row["year"]),
                        "local_path": row["local_path"],
                        "source_url": row["source_url"],
                        "is_candidate": True,
                    }
                    for row in database_documents
                    if row["local_path"].replace("\\", "/") not in {item["local_path"].replace("\\", "/") for item in documents}
                ] + ([{
                    "site_name": "대입정보포털 어디가",
                    "year": 2024,
                    "local_path": adiga["local_path"],
                    "source_url": adiga["detail_url"],
                    "is_candidate": True,
                }] if adiga and adiga.get("status") == "downloaded" and adiga["local_path"] not in {row["local_path"] for row in database_documents} else []),
                "source_rows": target["source_rows"],
            }
        )

    statuses = {status: sum(row["status"] == status for row in output) for status in (
        "grade_available", "results_without_grade", "source_checked_no_result", "candidate_not_extracted", "pdf_without_target_result", "not_on_nesin"
    )}
    summary = {
        "target_universities": len(output),
        "universities_with_pdf": sum(row["pdf_count"] > 0 for row in output),
        "universities_with_candidate_pdf": sum(row["candidate_pdf_count"] > 0 for row in output),
        "universities_with_results": sum(row["result_count"] > 0 for row in output),
        "universities_with_grade_results": sum(row["grade_result_count"] > 0 for row in output),
        "universities_with_source": sum(row["source_count"] > 0 for row in output),
        "statuses": statuses,
    }
    payload = {"summary": summary, "universities": output}
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    WEB_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    fields = ["university", "status", "cycles", "regions", "pdf_count", "candidate_pdf_count", "source_count", "result_count", "program_count", "grade_result_count", "high_confidence_count", "source_rows"]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: ", ".join(row[field]) if isinstance(row[field], list) else row[field] for field in fields} for row in output)
    print(json.dumps(summary, ensure_ascii=False))
    connection.close()


if __name__ == "__main__":
    main()
