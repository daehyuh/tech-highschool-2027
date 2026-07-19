from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
)


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        self._href = values.get("href") or values.get("onclick")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = re.sub(r"\s+", " ", html.unescape("".join(self._text))).strip()
        self.anchors.append({"href": html.unescape(self._href), "text": text})
        self._href = None
        self._text = []


def decode_page(payload: bytes, content_type: str) -> tuple[str, str]:
    candidates: list[str] = []
    header_match = re.search(r"charset=([^;\s]+)", content_type, re.I)
    if header_match:
        candidates.append(header_match.group(1).strip('"\''))
    head = payload[:4096].decode("ascii", errors="ignore")
    meta_match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", head, re.I)
    if meta_match:
        candidates.append(meta_match.group(1))
    candidates.extend(["utf-8", "cp949", "euc-kr"])
    for encoding in dict.fromkeys(candidates):
        try:
            return payload.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("utf-8", errors="replace"), "utf-8-replace"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="대학 입학처 게시판에서 상세글·첨부파일 링크를 검색합니다."
    )
    parser.add_argument("url")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--referer")
    parser.add_argument(
        "--context",
        action="store_true",
        help="검색어가 나타나는 원본 HTML 주변도 출력합니다.",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        help="검색된 HTTP(S) 링크의 첨부파일을 지정 폴더에 저장합니다.",
    )
    args = parser.parse_args()

    headers = {"User-Agent": USER_AGENT}
    if args.referer:
        headers["Referer"] = args.referer
    request = urllib.request.Request(args.url, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read()
        page, encoding = decode_page(payload, response.headers.get("Content-Type", ""))

    anchor_parser = AnchorParser()
    anchor_parser.feed(page)
    keywords = [keyword.casefold() for keyword in args.keyword]
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for anchor in anchor_parser.anchors:
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:")):
            continue
        absolute_url = urllib.parse.urljoin(args.url, href)
        searchable = f"{anchor['text']} {absolute_url}".casefold()
        if keywords and not any(keyword in searchable for keyword in keywords):
            continue
        key = (absolute_url, anchor["text"])
        if key in seen:
            continue
        seen.add(key)
        links.append({"text": anchor["text"], "url": absolute_url})

    if args.download_dir:
        args.download_dir.mkdir(parents=True, exist_ok=True)
        for index, link in enumerate(links, start=1):
            if not link["url"].startswith(("http://", "https://")):
                continue
            parsed_url = urllib.parse.urlparse(link["url"])
            query = urllib.parse.parse_qs(parsed_url.query)
            suggested = link["text"] or query.get("strFileName", [""])[0]
            if not suggested:
                suggested = Path(parsed_url.path).name or f"attachment-{index}"
            filename = re.sub(r'[<>:"/\\|?*]+', "_", suggested).strip(" .")
            if not filename:
                filename = f"attachment-{index}"
            destination = args.download_dir / filename
            encoded_url = urllib.parse.quote(link["url"], safe=":/?&=%")
            download_request = urllib.request.Request(
                encoded_url,
                headers={"User-Agent": USER_AGENT, "Referer": args.url},
            )
            with urllib.request.urlopen(download_request, timeout=90) as response:
                destination.write_bytes(response.read())
            link["saved_path"] = str(destination)

    contexts: list[str] = []
    if args.context:
        for keyword in args.keyword:
            for match in re.finditer(re.escape(keyword), page, re.I):
                start = max(0, match.start() - 300)
                end = min(len(page), match.end() + 500)
                snippet = re.sub(r"\s+", " ", page[start:end]).strip()
                contexts.append(snippet)
                if len(contexts) >= 20:
                    break
            if len(contexts) >= 20:
                break

    print(
        json.dumps(
            {
                "page_url": args.url,
                "encoding": encoding,
                "link_count": len(links),
                "links": links,
                "contexts": contexts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
