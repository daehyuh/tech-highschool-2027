from __future__ import annotations

import csv
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from lxml import html


ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = ROOT / "data" / "target_universities.json"
OUTPUT_ROOT = ROOT / "입시결과_공식" / "대입정보포털" / "2025"
REGISTRY_JSON = ROOT / "data" / "adiga_sources.json"
REGISTRY_CSV = ROOT / "data" / "adiga_sources.csv"
BASE = "https://www.adiga.kr"
LIST_URL = BASE + "/ucp/uvt/uni/univView.do?menuId=PCUVTINF2000"
SEARCH_URL = BASE + "/ucp/uvt/uni/univGroupAjax.do"
DETAIL_URL = BASE + "/ucp/uvt/uni/univDetailSelection.do?menuId=PCUVTINF2000&searchSyr=2025&unvCd={}"


def normalize(value: str) -> str:
    value = re.sub(r"\[[^]]+]", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value).replace("대학교", "대").replace("국립", "")


def query_name(target: str) -> str:
    aliases = {
        "덕성여대": "덕성여자대학교",
        "서울여대": "서울여자대학교",
        "숙명여대": "숙명여자대학교",
        "연세대(미래)": "연세대학교(미래)",
        "고려대(세종)": "고려대학교 세종캠퍼스",
    }
    if target in aliases:
        return aliases[target]
    base = re.sub(r"\([^)]*\)", "", target)
    if base.endswith("대"):
        base += "학교"
    return base


def campus_hint(target: str) -> str:
    match = re.search(r"\(([^)]+)\)", target)
    return match.group(1) if match else ""


def choose_match(target: str, matches: list[dict]) -> dict | None:
    if not matches:
        return None
    target_base = normalize(target)
    hint = campus_hint(target)

    def score(item: dict) -> tuple[int, int]:
        label = item["label"]
        value = 0
        if normalize(label) == target_base:
            value += 100
        elif target_base in normalize(label) or normalize(label) in target_base:
            value += 50
        if hint and hint in label:
            value += 80
        if not hint and any(term in label for term in ("본교", "서울캠퍼스")):
            value += 15
        if hint == "메디컬" and "글로벌" not in label:
            value += 10
        return value, -len(label)

    return max(matches, key=score)


def request(opener: urllib.request.OpenerDirector, url: str, data: dict | None = None) -> bytes:
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(
        url, data=encoded,
        headers={"User-Agent": "Mozilla/5.0 (compatible; admissions-research/1.0)"},
    )
    with opener.open(req, timeout=40) as response:
        return response.read()


def main() -> None:
    targets = json.loads(TARGET_PATH.read_text(encoding="utf-8"))["targets"]
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    list_body = request(opener, LIST_URL)
    document = html.fromstring(list_body.decode("utf-8"))
    csrf = document.xpath("string(//input[@name='_csrf']/@value)")
    if not csrf:
        raise RuntimeError("대입정보포털 CSRF 토큰을 찾지 못했습니다.")

    registry: list[dict] = []
    manual_codes = {
        "고려대(세종)": {"code": "0000070", "label": "고려대학교(세종)[분교]"},
        "연세대(미래)": {"code": "0000150", "label": "연세대학교(미래)[분교]"},
    }
    for index, target in enumerate(targets, start=1):
        university = target["university"]
        body = request(opener, SEARCH_URL, {
            "_csrf": csrf,
            "pagination.currentPage": "1",
            "pagination.cntPerPage": "30",
            "searchSyr": "2025",
            "searchTitle": query_name(university),
            "unvSeCd": "10",
        })
        search_document = html.fromstring(body.decode("utf-8"))
        matches = []
        for element in search_document.xpath("//input[contains(@class,'univGroupInput')]"):
            code = element.get("value", "")
            label = " ".join(element.getparent().xpath("string(.//label)").split())
            matches.append({"code": code, "label": re.sub(r"\d+건$", "", label).strip()})
        selected = choose_match(university, matches) or manual_codes.get(university)
        registry.append({
            "university": university,
            "query": query_name(university),
            "adiga_code": selected["code"] if selected else "",
            "adiga_label": selected["label"] if selected else "",
            "candidate_count": len(matches),
            "all_candidates": matches,
            "detail_url": DETAIL_URL.format(selected["code"]) if selected else "",
            "local_path": "",
            "status": "matched" if selected else "unmatched",
        })
        print(f"[{index:02d}/{len(targets)}] {university}: {selected['label'] if selected else 'UNMATCHED'}")
        time.sleep(0.08)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    by_code: dict[str, bytes] = {}
    for row in registry:
        code = row["adiga_code"]
        if not code:
            continue
        if code not in by_code:
            by_code[code] = request(opener, DETAIL_URL.format(code))
            time.sleep(0.08)
        path = OUTPUT_ROOT / f"{code}.html"
        if not path.exists():
            path.write_bytes(by_code[code])
        row["local_path"] = path.relative_to(ROOT).as_posix()
        row["status"] = "downloaded"

    payload = {
        "source": "대입정보포털 어디가",
        "admission_year": 2025,
        "target_count": len(registry),
        "matched_count": sum(bool(row["adiga_code"]) for row in registry),
        "unique_code_count": len({row["adiga_code"] for row in registry if row["adiga_code"]}),
        "sources": registry,
    }
    REGISTRY_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with REGISTRY_CSV.open("w", encoding="utf-8-sig", newline="") as output:
        fieldnames = ["university", "query", "adiga_code", "adiga_label", "candidate_count", "detail_url", "local_path", "status"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fieldnames} for row in registry)
    print(json.dumps({key: payload[key] for key in ("target_count", "matched_count", "unique_code_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
