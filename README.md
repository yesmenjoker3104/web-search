# web-search

DuckDuckGo で Web 検索を行い、上位ページの本文を取得して、LLM に要約させる **WebSearch プラグインの CLI** です。
[Assist-Chat](https://github.com/) のプラグイン機構から呼び出されることを想定しています。

## 動作の流れ

1. 検索語を受け取り、DuckDuckGo（`ddgs`）で検索する（既定 20 件、上限 20 件）
2. 上位 3 件のページ本文を取得する（1 ページあたり最大 1500 文字、取得できなければ概要だけ使う）
3. 検索結果をまとめたプロンプトを、標準出力の `llm_request` 行で **ホスト（Assist-Chat）に依頼する**
4. ホストが標準入力に返した `llm_response` を受け取り、回答を JSON で標準出力に出す

LLM を直接呼び出すのではなく、ホストに依頼する点がポイントです。モデルの選択や接続は Assist-Chat 側の責任になります。

## 必要な環境

- Windows
- Python 3.9 以上（開発時は 3.13 で確認）

## セットアップ

以下のコマンドは、リポジトリのルート（`web-search`）で実行します。
CLI 本体とテストが入っている内側の `web-search` はソースディレクトリです。

```powershell
cd web-search
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[build]
```

`-e .` でプロジェクトを開発モードで入れ、`[build]` で PyInstaller も入ります。
`.venv/` は `.gitignore` で除外されています。

## 使い方

CLI は次の形式で動きます。

```powershell
.\.venv\Scripts\python.exe web-search\websearch_cli.py search "検索したい内容" --limit 5
```

- `search <query>`: 検索して要約する
- `fetch <url>`: 指定された http(s) の URL のページを読んで要約する
- `--limit N`: 検索件数。1〜20 の範囲に丸められます（既定は 20）

ホストがいない単体実行では、`llm_request` 行が出た時点で標準入力が空のため、`{"ok": false, ...}` で終了します。

### 標準入出力のプロトコル

| 方向 | 形式 | 内容 |
|---|---|---|
| CLI → ホスト（標準出力） | `{"type":"llm_request","id":"1","prompt":"..."}` | LLM への依頼 |
| ホスト → CLI（標準入力） | `{"type":"llm_response","id":"1","text":"..."}` | 成功時の応答 |
| ホスト → CLI（標準入力） | `{"type":"llm_response","id":"1","error":"..."}` | 失敗時の応答 |
| CLI → ホスト（標準出力） | `{"ok":true,"answer":"..."}` または `{"ok":false,"error":"..."}` | 最終結果（1 行） |

- 標準出力には上記の JSON 行だけを出します。ログは標準エラーに出してください。
- 出力は `ensure_ascii` で ASCII に揃えています（日本語は `\uXXXX` になります）。
- 終了コードは成功時 `0`、失敗時 `1` です。

## exe のビルド

Assist-Chat のプラグインとして配布するため、PyInstaller で単一の exe にします。

```powershell
.\.venv\Scripts\pyinstaller.exe --onefile --name WebSearchCli web-search\websearch_cli.py
```

成果物は `dist\WebSearchCli.exe` に出ます。`build/`、`dist/`、`*.spec` は `.gitignore` で除外されています。

## テスト

標準ライブラリの `unittest` を使っています。追加のパッケージは不要です。

```powershell
Push-Location web-search
..\.venv\Scripts\python.exe -m unittest -v test_websearch_cli
Pop-Location
```

テストは次の 2 種類です。

- **単体テスト**: 検索・ページ取得・LLM 呼び出しを差し替えて、各関数の動作を確認
- **サブプロセステスト**: CLI を実際に起動し、標準入出力のプロトコルを確認（検索は偽の `ddgs` で代替し、ネットワークには出ません）

## バージョン管理

- バージョンは `web-search/websearch_cli.py` の `__version__` だけで管理します。`pyproject.toml` はここから読み込みます。
- 形式は [Semantic Versioning](https://semver.org/lang/ja/) です。
  - 互換性を壊す変更（プロトコル・終了コード・出力形式の変更）は、メジャーを上げます。
  - 機能追加は、マイナーを上げます。
  - 不具合修正は、パッチを上げます。
- 変更内容は `CHANGELOG.md` の `[Unreleased]` に書き、リリース時に版番号と日付を付けます。
- リリースは `v<バージョン>` のタグで行います（例: `v0.1.0`）。
- 確認は `.\.venv\Scripts\python.exe web-search\websearch_cli.py --version` で行います。

## ファイル構成

| パス | 内容 |
|---|---|
| `web-search/websearch_cli.py` | CLI 本体（`__version__` を含む） |
| `web-search/test_websearch_cli.py` | テスト |
| `plugin.json` | Assist-Chat 用のプラグイン定義（機械可読な契約） |
| `pyproject.toml` | プロジェクト情報と依存関係（版番号は CLI から読み込み） |
| `CHANGELOG.md` | 変更履歴 |
| `AGENTS.md` | 開発時の注意点（コーディングエージェント向け） |

## 関連

- プラグインの定義（`plugin.json`）は、このリポジトリで管理します。exe の配置先はまだ確定していません。
- プラグインの契約（`llm_request` / `llm_response` など）は Assist-Chat の `AGENTS.md` にも記載があります。
