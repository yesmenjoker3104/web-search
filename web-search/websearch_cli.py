"""WebSearch CLI: DuckDuckGo で検索 → 上位ページを取得 → LLM に要約させる。

stdout には制御行と最終 JSON だけを出す。ログは stderr へ出すこと。
"""
import argparse
import concurrent.futures
import html.parser
import json
import sys
import urllib.parse
import urllib.request

try:
    from ddgs import DDGS
except ImportError:  # 旧パッケージ名
    from duckduckgo_search import DDGS

RESULT_LIMIT = 20
FETCH_TOP_N = 3
PAGE_CHAR_LIMIT = 1500
FETCH_TIMEOUT_SEC = 5
# URL を直接読むときの上限。ホストの LLM は文脈長が短いため、本文はこの長さに抑える。
ARTICLE_CHAR_LIMIT = 4000
ARTICLE_READ_BYTES = 2 * 1024 * 1024
USER_AGENT = "Mozilla/5.0"
__version__ = "0.2.0"

_request_seq = 0


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=True), flush=True)


def ask_llm(prompt: str) -> str:
    """ホスト（Assist-Chat）の LLM に依頼し、応答テキストを返す。"""
    global _request_seq
    _request_seq += 1
    req_id = str(_request_seq)
    emit({"type": "llm_request", "id": req_id, "prompt": prompt})
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("ホストからの応答がありません")
    reply = json.loads(line)
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply.get("text", "")


class _TextExtractor(html.parser.HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def fetch_page_text(url: str) -> str:
    return _extract_text(_read_html(url, 512 * 1024))[:PAGE_CHAR_LIMIT]


def _extract_text(html_text: str) -> str:
    parser = _TextExtractor()
    parser.feed(html_text)
    return " ".join(parser.parts)


class _ArticleExtractor(_TextExtractor):
    """本文らしい部分を取り出す。<article>/<main> があればその中だけを優先する。"""

    SKIP_TAGS = _TextExtractor.SKIP_TAGS | {"nav", "header", "footer", "aside", "form"}
    MAIN_TAGS = {"article", "main"}

    def __init__(self):
        super().__init__()
        self.main_parts: list[str] = []
        self.title = ""
        self._main_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag in self.MAIN_TAGS:
            self._main_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag in self.MAIN_TAGS and self._main_depth:
            self._main_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        super().handle_data(data)
        if self._main_depth and not self._skip_depth and data.strip():
            self.main_parts.append(data.strip())


def _read_html(url: str, max_bytes: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as res:
        raw = res.read(max_bytes)
        charset = res.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def fetch_article(url: str) -> tuple[str, str]:
    """URL のページからタイトルと本文を取り出す。本文は ARTICLE_CHAR_LIMIT 字まで。"""
    parser = _ArticleExtractor()
    parser.feed(_read_html(url, ARTICLE_READ_BYTES))
    text = " ".join(parser.main_parts or parser.parts)
    return parser.title.strip(), text[:ARTICLE_CHAR_LIMIT]



def fetch_top_pages(hits: list[dict]) -> dict[int, str]:
    """上位ページを並列取得し、取得できた本文を検索順位で返す。"""
    top_hits = hits[:FETCH_TOP_N]
    if not top_hits:
        return {}

    pages = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(top_hits)) as executor:
        futures = {
            executor.submit(fetch_page_text, hit.get("href", "")): index
            for index, hit in enumerate(top_hits)
        }
        for future, index in futures.items():
            try:
                pages[index] = future.result()
            except Exception:
                pass  # 取得できないページは概要だけで扱う
    return pages


def _search_once(query: str, limit: int, region: str) -> list[dict]:
    try:
        hits = list(DDGS().text(query, max_results=limit, region=region))
    except Exception as exc:
        # ddgs は 0 件のとき例外を投げるので、それだけは「結果なし」として扱う
        if "No results found" in str(exc):
            return []
        raise
    # URL が空の結果は要約に使えないので除外する
    return [hit for hit in hits if hit.get("href")]


def search_web(query: str, limit: int) -> list[dict]:
    # 日本語の検索語は既定の地域だと、中身が空の結果しか返らないことがある。
    # その場合だけ日本の地域で検索し直す。
    hits = _search_once(query, limit, "wt-wt")
    if not hits:
        hits = _search_once(query, limit, "jp-jp")
    return hits


def cmd_search(query: str, limit: int) -> dict:
    if not query.strip():
        return {"ok": False, "error": "検索語が空です。"}
    try:
        hits = search_web(query, limit)
    except Exception as exc:
        return {"ok": False, "error": f"検索に失敗しました: {exc}"}
    if not hits:
        return {"ok": False, "error": "検索結果がありませんでした。"}

    page_texts = fetch_top_pages(hits)
    blocks = []
    for i, hit in enumerate(hits, start=1):
        title = hit.get("title", "")
        url = hit.get("href", "")
        snippet = hit.get("body", "")
        block = f"[{i}] {title}\nURL: {url}\n概要: {snippet}"
        if i - 1 in page_texts:
            block += f"\n本文: {page_texts[i - 1]}"
        blocks.append(block)

    prompt = (
        f"以下はWeb検索の結果です。依頼: {query}\n"
        "結果に書かれている内容だけを基に、日本語で簡潔に答えてください。"
        "結果に無い内容は推測しないでください。\n\n"
        + "\n\n".join(blocks)
    )
    try:
        answer = ask_llm(prompt)
    except Exception as exc:
        return {"ok": False, "error": f"要約に失敗しました: {exc}"}
    return {"ok": True, "answer": answer.strip() + "\n\n" + format_sources(hits)}


def is_http_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def cmd_fetch(url: str) -> dict:
    url = url.strip()
    if not is_http_url(url):
        return {"ok": False, "error": "http または https で始まるURLを指定してください。"}
    try:
        title, text = fetch_article(url)
    except Exception as exc:
        return {"ok": False, "error": f"ページを取得できませんでした: {exc}"}
    if not text.strip():
        return {"ok": False, "error": "ページから本文を取り出せませんでした。"}

    prompt = (
        f"以下はWebページの本文です。ページ: {title or url}\n\n"
        f"{text}\n\n"
        "上の本文の内容を、日本語で簡潔に要約してください。"
        "本文に書かれていない内容は推測しないでください。"
    )
    try:
        answer = ask_llm(prompt)
    except Exception as exc:
        return {"ok": False, "error": f"要約に失敗しました: {exc}"}
    source = [{"title": title or url, "href": url}]
    return {"ok": True, "answer": answer.strip() + "\n\n" + format_sources(source)}


def format_sources(hits: list[dict]) -> str:
    # URL は単独の行に置く。アプリ側でクリックできるリンクになり、句読点も混ざらない。
    lines = ["出典:"]
    for i, hit in enumerate(hits, start=1):
        title = " ".join(str(hit.get("title", "")).split()) or "無題"
        lines.append(f"[{i}] {title}")
        lines.append(hit.get("href", ""))
    return "\n".join(lines)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main() -> int:
    parser = _ArgumentParser(prog="WebSearchCli")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=RESULT_LIMIT)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("url")
    try:
        args = parser.parse_args()
    except ValueError as exc:
        emit({"ok": False, "error": f"引数エラー: {exc}"})
        return 1

    if args.cmd == "fetch":
        result = cmd_fetch(args.url)
    else:
        limit = max(1, min(args.limit, RESULT_LIMIT))
        result = cmd_search(args.query, limit)
    emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
