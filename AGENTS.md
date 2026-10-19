# AGENTS.md

このリポジトリで作業するコーディングエージェント向けの指示です。

## プロジェクト概要

- `web-search` は、DuckDuckGo 検索と LLM 要約を行う WebSearch プラグインの CLI です。
- ホスト（Assist-Chat）の plugin_manager から子プロセスとして起動されます。
- 実装本体は `websearch_cli.py` のみです。テストは `test_websearch_cli.py` にあります。

## 変更時の制約

- **標準出力に出してよいのは JSON 行だけです。** ログや進捗は標準エラーに出してください。`print()` でデバッグ文字列を出すと、ホストが結果を解釈できなくなります。
- **`llm_request` / `llm_response` のプロトコルを変えるときは、ホスト側（Assist-Chat の `backend/plugin_manager.py`）と同時に確認してください。** 片方だけ変えると、LLM 要約が動かなくなります。
- **`ensure_ascii=True` を維持してください。** 日本語を含めても出力は 1 行の ASCII である前提になっています（テスト `test_output_is_single_ascii_line` で確認しています）。
- **終了コードの約束**: 成功は `0`、失敗は `1`。結果 JSON は終了コードに関係なく必ず 1 行出します。
- **検索件数は 1〜20 に丸めます。** `RESULT_LIMIT` を超える値を許可しないでください。
- **外部通信の上限**: ページ取得は上位 `FETCH_TOP_N` 件、1 ページ `PAGE_CHAR_LIMIT` 文字、タイムアウト `FETCH_TIMEOUT_SEC` 秒です。これらを増やす場合は、LLM に渡すプロンプトの長さも考えてください。

## 開発コマンド

作業前に `.venv` が無ければ作成してください。

```powershell
cd web-search
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[build]
```

テストは次で実行します。

```powershell
cd web-search
.\.venv\Scripts\python.exe -m unittest -v test_websearch_cli
```

exe をビルドする場合は次を使います。

```powershell
cd web-search
.\.venv\Scripts\pyinstaller.exe --onefile --name WebSearchCli websearch_cli.py
```

## バージョン管理

- 版番号の出典は `web-search/websearch_cli.py` の `__version__` だけです。`pyproject.toml` は `dynamic` でここを参照しています。二か所に書かないでください。
- SemVer に従ってください。プロトコル・終了コード・出力形式を変えたら、メジャーを上げます。
- 変更は `CHANGELOG.md` の `[Unreleased]` に書いてください。リリース時に版番号と日付を付けます。
- リリースは `v<バージョン>` のタグで行います。タグは、コミットとプッシュの承認を得てから付けてください。

## コミット

- コミットは `web-search` のルートで行います。`.venv/` や `build/` などは `.gitignore` で除外されています。
- メッセージには、変更の内容と影響範囲を書いてください。

## テストの書き方

- 標準ライブラリの `unittest` のみを使います。pytest など新しいパッケージを追加しないでください。
- 検索（`search_web`）、ページ取得（`fetch_page_text`）、LLM 呼び出し（`ask_llm`）は `unittest.mock` で差し替えてください。テストから実ネットワークに出ないようにします。
- サブプロセステストは偽の `ddgs.py` を一時ディレクトリに置き、`PYTHONPATH` で読ませています。この方法を維持してください。
- 既知の不具合は `@unittest.expectedFailure` で記録しています。直したら、このデコレータを外してください。

## 作業のルール

- 変更は必要最小限にしてください。関係のないリファクタリングは含めないでください。
- コミットとプッシュは、ユーザーの承認を得てから行ってください。
- 一時ファイルは作業後に削除してください。
- コメントは、意図が分かりにくい箇所にだけ書いてください。
