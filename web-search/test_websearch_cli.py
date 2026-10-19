"""websearch_cli.py のテスト（標準ライブラリの unittest のみ使用）。

実行例（web-search\\web-search で）:
    ..\\.venv\\Scripts\\python.exe -m unittest -v test_websearch_cli
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from unittest import mock

import websearch_cli as cli

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "websearch_cli.py")

HITS = [
    {"title": "記事1", "href": "https://example.com/1", "body": "概要1"},
    {"title": "記事2", "href": "https://example.com/2", "body": "概要2"},
    {"title": "記事3", "href": "https://example.com/3", "body": "概要3"},
    {"title": "記事4", "href": "https://example.com/4", "body": "概要4"},
    {"title": "記事5", "href": "https://example.com/5", "body": "概要5"},
]

# 実ネットワークに出ないよう、href を空にして取得を即失敗させる
FAKE_DDGS = textwrap.dedent('''
    class DDGS:
        def text(self, query, max_results=10):
            return [{"title": "テスト記事", "href": "", "body": "概要テキスト"}][:max_results]
''')


class CmdSearchTest(unittest.TestCase):
    def test_empty_query_returns_error_without_searching(self):
        with mock.patch.object(cli, "search_web") as search:
            result = cli.cmd_search("   ", 5)
        search.assert_not_called()
        self.assertEqual(result, {"ok": False, "error": "検索語が空です。"})

    def test_search_exception_is_reported(self):
        with mock.patch.object(cli, "search_web", side_effect=RuntimeError("boom")):
            result = cli.cmd_search("q", 5)
        self.assertFalse(result["ok"])
        self.assertIn("検索に失敗しました", result["error"])
        self.assertIn("boom", result["error"])

    def test_no_hits_returns_error(self):
        with mock.patch.object(cli, "search_web", return_value=[]):
            result = cli.cmd_search("q", 5)
        self.assertEqual(result, {"ok": False, "error": "検索結果がありませんでした。"})

    @unittest.expectedFailure
    def test_library_no_results_exception_is_reported_as_no_results(self):
        # 既知の不具合: ddgs は 0 件のとき例外を投げるため、「検索結果がありませんでした」に到達しない
        with mock.patch.object(cli, "search_web", side_effect=Exception("No results found.")):
            result = cli.cmd_search("q", 5)
        self.assertEqual(result["error"], "検索結果がありませんでした。")

    def test_success_builds_prompt_and_returns_stripped_answer(self):
        with mock.patch.object(cli, "search_web", return_value=HITS[:3]), \
             mock.patch.object(cli, "fetch_page_text", return_value="本文テキスト"), \
             mock.patch.object(cli, "ask_llm", return_value="  回答です。\n") as ask:
            result = cli.cmd_search("依頼内容", 3)

        self.assertEqual(result, {"ok": True, "answer": "回答です。"})
        prompt = ask.call_args.args[0]
        self.assertIn("依頼内容", prompt)
        for hit in HITS[:3]:
            self.assertIn(hit["title"], prompt)
            self.assertIn(hit["href"], prompt)
            self.assertIn(hit["body"], prompt)
        self.assertIn("本文: 本文テキスト", prompt)

    def test_only_top_hits_are_fetched(self):
        with mock.patch.object(cli, "search_web", return_value=HITS), \
             mock.patch.object(cli, "fetch_page_text", return_value="x") as fetch, \
             mock.patch.object(cli, "ask_llm", return_value="ok"):
            cli.cmd_search("q", 5)

        fetched = [c.args[0] for c in fetch.call_args_list]
        self.assertEqual(fetched, [h["href"] for h in HITS[:cli.FETCH_TOP_N]])

    def test_unfetchable_page_falls_back_to_snippet(self):
        with mock.patch.object(cli, "search_web", return_value=HITS[:2]), \
             mock.patch.object(cli, "fetch_page_text", side_effect=OSError("timeout")), \
             mock.patch.object(cli, "ask_llm", return_value="ok") as ask:
            result = cli.cmd_search("q", 2)

        self.assertTrue(result["ok"])
        prompt = ask.call_args.args[0]
        self.assertIn("概要: 概要1", prompt)
        self.assertNotIn("本文:", prompt)

    def test_llm_failure_is_reported(self):
        with mock.patch.object(cli, "search_web", return_value=HITS[:1]), \
             mock.patch.object(cli, "fetch_page_text", return_value="x"), \
             mock.patch.object(cli, "ask_llm", side_effect=RuntimeError("LLM down")):
            result = cli.cmd_search("q", 1)

        self.assertFalse(result["ok"])
        self.assertIn("要約に失敗しました", result["error"])
        self.assertIn("LLM down", result["error"])


class SearchWebTest(unittest.TestCase):
    def test_passes_query_and_limit_to_ddgs(self):
        fake = mock.MagicMock()
        fake.return_value.text.return_value = iter(HITS[:2])
        with mock.patch.object(cli, "DDGS", fake):
            result = cli.search_web("テスト", 2)

        fake.return_value.text.assert_called_once_with("テスト", max_results=2)
        self.assertEqual(result, HITS[:2])


class TextExtractorTest(unittest.TestCase):
    def _extract(self, html_text):
        parser = cli._TextExtractor()
        parser.feed(html_text)
        return " ".join(parser.parts)

    def test_skips_script_style_and_noscript(self):
        page = ("<html><head><style>p{}</style><script>var x=1;</script></head>"
                "<body><p>本文</p><noscript>無効</noscript><div> 次 </div></body></html>")
        self.assertEqual(self._extract(page), "本文 次")

    def test_blank_text_is_ignored(self):
        self.assertEqual(self._extract("<p>  </p><p>A</p>"), "A")


class FetchPageTextTest(unittest.TestCase):
    def _fake_urlopen(self, body: bytes, charset: str = "utf-8"):
        res = mock.MagicMock()
        res.__enter__.return_value = res
        res.read.return_value = body
        res.headers.get_content_charset.return_value = charset
        return mock.patch.object(cli.urllib.request, "urlopen", return_value=res)

    def test_decodes_declared_charset(self):
        body = "<p>日本語</p>".encode("shift_jis")
        with self._fake_urlopen(body, "shift_jis"):
            self.assertEqual(cli.fetch_page_text("https://example.com"), "日本語")

    def test_text_is_truncated_to_limit(self):
        body = ("<p>" + "a" * 5000 + "</p>").encode("utf-8")
        with self._fake_urlopen(body):
            self.assertEqual(len(cli.fetch_page_text("https://example.com")), cli.PAGE_CHAR_LIMIT)

    def test_request_uses_user_agent_and_timeout(self):
        with self._fake_urlopen(b"<p>x</p>") as urlopen:
            cli.fetch_page_text("https://example.com")

        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "https://example.com")
        self.assertEqual(req.get_header("User-agent"), cli.USER_AGENT)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], cli.FETCH_TIMEOUT_SEC)


class AskLlmTest(unittest.TestCase):
    def setUp(self):
        cli._request_seq = 0

    def test_emits_request_and_returns_text(self):
        out = io.StringIO()
        stdin = io.StringIO('{"type":"llm_response","id":"1","text":"はい"}\n')
        with mock.patch.object(cli.sys, "stdin", stdin), redirect_stdout(out):
            text = cli.ask_llm("質問")

        self.assertEqual(text, "はい")
        self.assertEqual(json.loads(out.getvalue()),
                         {"type": "llm_request", "id": "1", "prompt": "質問"})

    def test_request_ids_increase(self):
        out = io.StringIO()
        stdin = io.StringIO('{"text":"a"}\n{"text":"b"}\n')
        with mock.patch.object(cli.sys, "stdin", stdin), redirect_stdout(out):
            cli.ask_llm("1つ目")
            cli.ask_llm("2つ目")

        ids = [json.loads(line)["id"] for line in out.getvalue().splitlines()]
        self.assertEqual(ids, ["1", "2"])

    def test_error_reply_raises(self):
        stdin = io.StringIO('{"type":"llm_response","id":"1","error":"モデル未接続"}\n')
        with mock.patch.object(cli.sys, "stdin", stdin), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "モデル未接続"):
                cli.ask_llm("質問")

    def test_closed_stdin_raises(self):
        with mock.patch.object(cli.sys, "stdin", io.StringIO("")), redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                cli.ask_llm("質問")


class MainTest(unittest.TestCase):
    def _main(self, argv, result=None):
        out = io.StringIO()
        result = result if result is not None else {"ok": True, "answer": ""}
        with mock.patch.object(cli.sys, "argv", ["WebSearchCli", *argv]), \
             mock.patch.object(cli, "cmd_search", return_value=result) as cmd, \
             redirect_stdout(out):
            code = cli.main()
        return code, cmd, out.getvalue()

    def test_success_exits_zero_and_prints_json(self):
        code, _, out = self._main(["search", "q"], {"ok": True, "answer": "回答"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"ok": True, "answer": "回答"})

    def test_failure_exits_one(self):
        code, _, _ = self._main(["search", "q"], {"ok": False, "error": "x"})
        self.assertEqual(code, 1)

    def test_output_is_single_ascii_line(self):
        _, _, out = self._main(["search", "q"], {"ok": True, "answer": "日本語の回答"})
        self.assertTrue(out.isascii())
        self.assertEqual(len(out.strip().splitlines()), 1)

    def test_version_option_prints_version_and_exits_zero(self):
        out = io.StringIO()
        with mock.patch.object(cli.sys, "argv", ["WebSearchCli", "--version"]), \
             redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                cli.main()
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"WebSearchCli {cli.__version__}")

    def test_default_limit_is_result_limit(self):
        _, cmd, _ = self._main(["search", "q"])
        cmd.assert_called_once_with("q", cli.RESULT_LIMIT)

    def test_limit_is_clamped_to_range(self):
        cases = [("5", 5), ("999", cli.RESULT_LIMIT), ("0", 1), ("-3", 1)]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                _, cmd, _ = self._main(["search", "q", "--limit", raw])
                cmd.assert_called_once_with("q", expected)


class ScriptProtocolTest(unittest.TestCase):
    """実際にサブプロセスとして起動し、標準入出力のプロトコルを確認する。"""

    def _run_script(self, args, reply=None):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "ddgs.py"), "w", encoding="utf-8") as f:
                f.write(FAKE_DDGS)
            env = {**os.environ, "PYTHONPATH": tmp, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(
                [sys.executable, SCRIPT, *args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", env=env,
            )
            try:
                request = json.loads(proc.stdout.readline())
                reply_line = None
                if reply is not None:
                    reply_line = json.dumps({"type": "llm_response", "id": request["id"], **reply}) + "\n"
                rest, _ = proc.communicate(input=reply_line, timeout=30)
            finally:
                if proc.poll() is None:
                    proc.kill()
        return request, proc.returncode, rest

    def test_round_trip_over_stdio(self):
        request, code, rest = self._run_script(
            ["search", "テスト依頼", "--limit", "2"], {"text": "要約結果"})

        self.assertEqual(request["type"], "llm_request")
        self.assertIn("テスト記事", request["prompt"])
        self.assertIn("概要テキスト", request["prompt"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(rest.strip()), {"ok": True, "answer": "要約結果"})

    def test_llm_error_reply_exits_one(self):
        _, code, rest = self._run_script(["search", "テスト依頼"], {"error": "モデル未接続"})

        self.assertEqual(code, 1)
        result = json.loads(rest.strip())
        self.assertFalse(result["ok"])
        self.assertIn("モデル未接続", result["error"])

    def test_host_closing_stdin_exits_one(self):
        _, code, rest = self._run_script(["search", "テスト依頼"], reply=None)

        self.assertEqual(code, 1)
        result = json.loads(rest.strip())
        self.assertFalse(result["ok"])
        self.assertIn("要約に失敗しました", result["error"])


if __name__ == "__main__":
    unittest.main()
