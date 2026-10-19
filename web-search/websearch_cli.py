"""WebSearch CLI: DuckDuckGo で検索 → 上位ページを取得 → LLM に要約させる。

stdout には制御行と最終 JSON だけを出す。ログは stderr へ出すこと。
"""
import argparse
import html.parser
import json
import sys
import urllib.request

try:
    from ddgs import DDGS
except ImportError:  # 旧パッケージ名
    from duckduckgo_search import DDGS

RESULT_LIMIT = 20
FETCH_TOP_N = 3
PAGE_CHAR_LIMIT = 1500
FETCH_TIMEOUT_SEC = 5
USER_AGENT = "Mozilla/5.0"
__version__ = "0.1.0"

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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as res:
        raw = res.read(512 * 1024)
        charset = res.headers.get_content_charset() or "utf-8"
    parser = _TextExtractor()
    parser.feed(raw.decode(charset, errors="replace"))
    return " ".join(parser.parts)[:PAGE_CHAR_LIMIT]


def search_web(query: str, limit: int) -> list[dict]:
    return list(DDGS().text(query, max_results=limit))


def cmd_search(query: str, limit: int) -> dict:
    if not query.strip():
        return {"ok": False, "error": "検索語が空です。"}
    try:
        hits = search_web(query, limit)
    except Exception as exc:
        return {"ok": False, "error": f"検索に失敗しました: {exc}"}
    if not hits:
        return {"ok": False, "error": "検索結果がありませんでした。"}

    blocks = []
    for i, hit in enumerate(hits, start=1):
        title = hit.get("title", "")
        url = hit.get("href", "")
        snippet = hit.get("body", "")
        block = f"[{i}] {title}\nURL: {url}\n概要: {snippet}"
        if i <= FETCH_TOP_N:
            try:
                block += f"\n本文: {fetch_page_text(url)}"
            except Exception:
                pass  # 取得できないページは概要だけで扱う
        blocks.append(block)

    prompt = (
        f"以下はWeb検索の結果です。依頼: {query}\n"
        "結果に書かれている内容だけを基に、日本語で簡潔に答えてください。"
        "結果に無い内容は推測しないでください。"
        "最後に根拠にしたURLを箇条書きで付けてください。\n\n"
        + "\n\n".join(blocks)
    )
    try:
        answer = ask_llm(prompt)
    except Exception as exc:
        return {"ok": False, "error": f"要約に失敗しました: {exc}"}
    return {"ok": True, "answer": answer.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(prog="WebSearchCli")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=RESULT_LIMIT)
    args = parser.parse_args()

    limit = max(1, min(args.limit, RESULT_LIMIT))
    result = cmd_search(args.query, limit)
    emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
