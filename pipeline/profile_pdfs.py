from __future__ import annotations

import json
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "입시결과_PDF"
OUTPUT = ROOT / "data" / "pdf_profile.json"

KEYWORDS = {
    "vocational": re.compile(r"특성화\s*고|특성화고교|특성화고졸|특성화고\s*출신|특성화고\s*동일계"),
    "grade": re.compile(r"등급|교과성적|학생부"),
    "department": re.compile(r"모집단위|학과|전공"),
    "cut": re.compile(r"50\s*%|70\s*%|80\s*%|컷|cut", re.I),
}


def profile(path_text: str) -> dict:
    path = Path(path_text)
    result = {
        "path": str(path.relative_to(ROOT)),
        "pages": 0,
        "keyword_pages": [],
        "error": None,
    }
    try:
        reader = PdfReader(path, strict=False)
        result["pages"] = len(reader.pages)
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            normalized = re.sub(r"\s+", " ", text)
            matches = [name for name, pattern in KEYWORDS.items() if pattern.search(normalized)]
            if "vocational" in matches:
                hit = KEYWORDS["vocational"].search(normalized)
                start = max(0, (hit.start() if hit else 0) - 220)
                end = min(len(normalized), (hit.end() if hit else 0) + 500)
                result["keyword_pages"].append({
                    "page": index + 1,
                    "matches": matches,
                    "snippet": normalized[start:end],
                })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    paths = sorted(PDF_ROOT.rglob("*.pdf"))
    records = []
    with ProcessPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(profile, str(path)): path for path in paths}
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda row: row["path"])
    summary = {
        "documents": len(records),
        "documents_with_vocational_keyword": sum(bool(row["keyword_pages"]) for row in records),
        "candidate_pages": sum(len(row["keyword_pages"]) for row in records),
        "errors": sum(bool(row["error"]) for row in records),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"summary": summary, "documents": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
