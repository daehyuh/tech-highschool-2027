from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "입시결과_PDF"
INDEX_PATH = OUTPUT_DIR / "collection_index.csv"
SUMMARY_PATH = OUTPUT_DIR / "collection_summary.json"
BASE_URL = "https://www.nesin.com/"
DETAIL_URL = "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi_detail&code={}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138 Safari/537.36"


TARGETS = json.loads(r'''[{"sourceName":"건국대","code":"3","siteName":"건국대학교(서울)"},{"sourceName":"광운대","code":"7","siteName":"광운대학교"},{"sourceName":"덕성여대","code":"11","siteName":"덕성여자대학교"},{"sourceName":"명지대","code":"14","siteName":"명지대학교(서울)"},{"sourceName":"삼육대","code":"15","siteName":"삼육대학교"},{"sourceName":"서강대","code":"17","siteName":"서강대학교"},{"sourceName":"서경대","code":"18","siteName":"서경대학교"},{"sourceName":"서울대","code":"21","siteName":"서울대학교"},{"sourceName":"서울여대","code":"24","siteName":"서울여자대학교"},{"sourceName":"성공회대","code":"25","siteName":"성공회대학교"},{"sourceName":"숙명여대","code":"29","siteName":"숙명여자대학교"},{"sourceName":"한성대","code":"41","siteName":"한성대학교"},{"sourceName":"가천대(메디컬)","code":"45","siteName":"가천대학교(메디컬)"},{"sourceName":"가천대","code":"48","siteName":"가천대학교(글로벌)"},{"sourceName":"가톨릭대","code":"405","siteName":"가톨릭대학교(성심)"},{"sourceName":"강남대","code":"46","siteName":"강남대학교"},{"sourceName":"국립한국교통대(의왕)","code":"346","siteName":"한국교통대학교(의왕)"},{"sourceName":"동양대","code":"415","siteName":"동양대학교(북서울)"},{"sourceName":"대진대","code":"51","siteName":"대진대학교"},{"sourceName":"명지대(용인)","code":"52","siteName":"명지대학교(용인)"},{"sourceName":"서울신학대","code":"53","siteName":"서울신학대학교"},{"sourceName":"성결대","code":"55","siteName":"성결대학교"},{"sourceName":"수원대","code":"57","siteName":"수원대학교"},{"sourceName":"신한대","code":"408","siteName":"신한대학교(의정부)"},{"sourceName":"신한대","code":"216","siteName":"신한대학교(동두천)"},{"sourceName":"안양대","code":"61","siteName":"안양대학교(안양)"},{"sourceName":"용인대","code":"62","siteName":"용인대학교"},{"sourceName":"을지대","code":"329","siteName":"을지대학교(성남)"},{"sourceName":"을지대","code":"420","siteName":"을지대학교(의정부)"},{"sourceName":"중부대(고양)","code":"413","siteName":"중부대학교(고양)"},{"sourceName":"칼빈대","code":"68","siteName":"칼빈대학교"},{"sourceName":"평택대","code":"69","siteName":"평택대학교"},{"sourceName":"한경국립대","code":"71","siteName":"한경국립대학교(안성)"},{"sourceName":"한경국립대","code":"427","siteName":"한경국립대학교(평택)"},{"sourceName":"한국공학대","code":"72","siteName":"한국공학대학교"},{"sourceName":"한세대","code":"76","siteName":"한세대학교"},{"sourceName":"한신대","code":"77","siteName":"한신대학교"},{"sourceName":"협성대","code":"79","siteName":"협성대학교"},{"sourceName":"화성의과학대","code":"220","siteName":"화성의과학대학교"},{"sourceName":"강원대","code":"81","siteName":"강원대학교(춘천)"},{"sourceName":"강원대","code":"86","siteName":"강원대학교(삼척)"},{"sourceName":"국립강릉원주대","code":"80","siteName":"강원대학교(강릉)"},{"sourceName":"국립강릉원주대","code":"234","siteName":"강원대학교(원주)"},{"sourceName":"연세대(미래)","code":"88","siteName":"연세대학교(원주)"},{"sourceName":"한라대","code":"93","siteName":"한라대학교"},{"sourceName":"충남대","code":"124","siteName":"충남대학교"},{"sourceName":"고려대(세종)","code":"97","siteName":"고려대학교(세종)"},{"sourceName":"국립공주대","code":"99","siteName":"국립공주대학교"},{"sourceName":"한국기술교육대","code":"129","siteName":"한국기술교육대학교"},{"sourceName":"충북대","code":"125","siteName":"충북대학교"},{"sourceName":"경북대","code":"167","siteName":"경북대학교(대구)"},{"sourceName":"계명대","code":"173","siteName":"계명대학교"},{"sourceName":"영남대","code":"185","siteName":"영남대학교"},{"sourceName":"국립금오공과대","code":"175","siteName":"국립금오공과대학교"},{"sourceName":"동의대","code":"192","siteName":"동의대학교"},{"sourceName":"동서대","code":"190","siteName":"동서대학교"},{"sourceName":"동명대","code":"189","siteName":"동명대학교"},{"sourceName":"경성대","code":"169","siteName":"경성대학교"},{"sourceName":"동아대","code":"191","siteName":"동아대학교"},{"sourceName":"부산대","code":"196","siteName":"부산대학교"},{"sourceName":"울산대","code":"205","siteName":"울산대학교"},{"sourceName":"경상국립대","code":"201","siteName":"경상국립대학교"},{"sourceName":"인제대","code":"206","siteName":"인제대학교"},{"sourceName":"전남대","code":"155","siteName":"전남대학교(광주)"},{"sourceName":"조선대","code":"159","siteName":"조선대학교"},{"sourceName":"국립순천대","code":"149","siteName":"국립순천대학교"},{"sourceName":"전남대(여수)","code":"150","siteName":"전남대학교(여수)"},{"sourceName":"전북대","code":"156","siteName":"전북대학교(전주)"},{"sourceName":"국립군산대","code":"140","siteName":"국립군산대학교"},{"sourceName":"원광대","code":"154","siteName":"원광대학교"},{"sourceName":"제주대","code":"90","siteName":"제주대학교"},{"sourceName":"고려대","code":"6","siteName":"고려대학교(서울)"},{"sourceName":"경희대","code":"5","siteName":"경희대학교(서울)"},{"sourceName":"경희대","code":"50","siteName":"경희대학교(국제)"},{"sourceName":"연세대","code":"31","siteName":"연세대학교(서울)"},{"sourceName":"성균관대","code":"26","siteName":"성균관대학교"},{"sourceName":"한양대","code":"42","siteName":"한양대학교(서울)"},{"sourceName":"중앙대","code":"34","siteName":"중앙대학교(서울)"},{"sourceName":"중앙대","code":"67","siteName":"중앙대학교(다빈치)"},{"sourceName":"서울시립대","code":"23","siteName":"서울시립대학교"},{"sourceName":"숭실대","code":"30","siteName":"숭실대학교"},{"sourceName":"세종대","code":"28","siteName":"세종대학교"},{"sourceName":"홍익대","code":"44","siteName":"홍익대학교(서울)"},{"sourceName":"인천대","code":"65","siteName":"인천대학교"},{"sourceName":"인하대","code":"66","siteName":"인하대학교"},{"sourceName":"아주대","code":"59","siteName":"아주대학교"},{"sourceName":"한국항공대","code":"75","siteName":"한국항공대학교"},{"sourceName":"한양대(ERICA)","code":"78","siteName":"한양대학교(ERICA)"}]''')


def request_bytes(url: str, attempts: int = 3) -> tuple[bytes, dict[str, str]]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": BASE_URL})
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read(), dict(response.headers.items())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}: {last_error}")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def extract_attachments(page: bytes) -> list[dict[str, str]]:
    # The page declares UTF-8 in HTML but the HTTP response and actual bytes are EUC-KR/CP949.
    text = page.decode("cp949", errors="replace")
    table = next((x for x in re.findall(r"<table\b.*?</table>", text, flags=re.I | re.S)
                  if "입시결과" in x and "학년도" in x), "")
    attachments: list[dict[str, str]] = []
    for row in re.findall(r"<tr\b.*?</tr>", table, flags=re.I | re.S):
        cells = re.findall(r"<td\b.*?</td>", row, flags=re.I | re.S)
        if len(cells) < 4:
            continue
        match = re.search(r"href\s*=\s*['\"]([^'\"]+)['\"]", cells[3], flags=re.I)
        if not match:
            continue
        attachments.append({
            "year": clean_text(cells[0]),
            "url": urllib.parse.urljoin(BASE_URL, html.unescape(match.group(1))),
        })
    return attachments


def safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .")
    return re.sub(r"\s+", "_", value)[:100]


def validate_pdf(path: Path) -> tuple[bool, int | None, str]:
    try:
        if path.read_bytes()[:5] != b"%PDF-":
            return False, None, "missing_pdf_signature"
        reader = PdfReader(str(path), strict=False)
        return True, len(reader.pages), "ok"
    except Exception as exc:
        return False, None, f"pypdf_error:{type(exc).__name__}"


def fetch_detail(target: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]], str]:
    detail_url = DETAIL_URL.format(target["code"])
    try:
        page, _ = request_bytes(detail_url)
        return target, extract_attachments(page), "ok"
    except Exception as exc:
        return target, [], f"detail_error:{type(exc).__name__}"


def download_pdf(item: dict[str, str]) -> dict[str, str | int | bool | None]:
    target_dir = OUTPUT_DIR / safe_name(item["source_name"]) / safe_name(item["site_name"])
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_name(item['site_name'])}__{safe_name(item['year'])}__입시결과.pdf"
    path = target_dir / filename
    try:
        data, headers = request_bytes(item["url"])
        path.write_bytes(data)
        valid, pages, validation = validate_pdf(path)
        sha256 = hashlib.sha256(data).hexdigest()
        return {**item, "status": "downloaded" if valid else "invalid_pdf", "local_path": str(path.relative_to(ROOT)),
                "bytes": len(data), "pages": pages, "sha256": sha256, "validation": validation,
                "content_type": headers.get("Content-Type", "")}
    except Exception as exc:
        return {**item, "status": "download_error", "local_path": "", "bytes": None, "pages": None,
                "sha256": "", "validation": f"{type(exc).__name__}:{exc}", "content_type": ""}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    detail_rows: list[tuple[dict[str, str], list[dict[str, str]], str]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_detail, target) for target in TARGETS]
        for future in as_completed(futures):
            detail_rows.append(future.result())

    index_rows: list[dict[str, str | int | bool | None]] = []
    pdf_items: list[dict[str, str]] = []
    for target, attachments, detail_status in sorted(detail_rows, key=lambda x: (x[0]["sourceName"], x[0]["siteName"])):
        detail_url = DETAIL_URL.format(target["code"])
        if not attachments:
            index_rows.append({"source_name": target["sourceName"], "site_name": target["siteName"], "site_code": target["code"],
                               "year": "", "format": "", "status": "no_attachment" if detail_status == "ok" else detail_status,
                               "source_url": detail_url, "local_path": "", "bytes": None, "pages": None,
                               "sha256": "", "validation": "", "content_type": ""})
        for attachment in attachments:
            is_pdf = bool(re.search(r"\.pdf(?:$|[&#])", attachment["url"], flags=re.I))
            item = {"source_name": target["sourceName"], "site_name": target["siteName"], "site_code": target["code"],
                    "year": attachment["year"], "format": "pdf" if is_pdf else "other", "url": attachment["url"],
                    "source_url": detail_url}
            if is_pdf:
                pdf_items.append(item)
            else:
                index_rows.append({**item, "status": "excluded_non_pdf", "local_path": "", "bytes": None, "pages": None,
                                   "sha256": "", "validation": "", "content_type": ""})

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(download_pdf, item) for item in pdf_items]
        for future in as_completed(futures):
            index_rows.append(future.result())

    index_rows.append({"source_name": "서울기독대", "site_name": "", "site_code": "", "year": "", "format": "",
                       "status": "site_not_listed", "source_url": "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi",
                       "local_path": "", "bytes": None, "pages": None, "sha256": "", "validation": "", "content_type": ""})

    index_rows.sort(key=lambda x: (str(x.get("source_name", "")), str(x.get("site_name", "")), str(x.get("year", ""))))
    fields = ["source_name", "site_name", "site_code", "year", "format", "status", "source_url", "url", "local_path",
              "bytes", "pages", "sha256", "validation", "content_type"]
    with INDEX_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(index_rows)

    summary = {
        "source_workbook": "2027_특성화고_모집대학.xlsm",
        "source_platform": "https://www.nesin.com/html/?dir1=menu03&dir2=university_rating_susi",
        "target_university_names": 82,
        "matched_detail_pages": len(TARGETS),
        "downloaded_valid_pdfs": sum(row.get("status") == "downloaded" for row in index_rows),
        "invalid_pdfs": sum(row.get("status") == "invalid_pdf" for row in index_rows),
        "download_errors": sum(row.get("status") == "download_error" for row in index_rows),
        "excluded_non_pdf_attachments": sum(row.get("status") == "excluded_non_pdf" for row in index_rows),
        "detail_pages_without_attachments": sum(row.get("status") == "no_attachment" for row in index_rows),
        "site_not_listed": [row["source_name"] for row in index_rows if row.get("status") == "site_not_listed"],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
