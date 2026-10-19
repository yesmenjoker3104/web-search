# Changelog

このプロジェクトの変更履歴です。
書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

## [0.1.0] - 2026-10-19

### Added

- DuckDuckGo（`ddgs`）による Web 検索と、上位 3 件のページ本文の取得
- LLM への要約依頼を標準入出力で行う `llm_request` / `llm_response` プロトコル
- `search` サブコマンドと `--limit`（1〜20 に丸め、既定は 20）
- `--version` オプション
- `unittest` によるテスト（単体テストとサブプロセステスト）
- PyInstaller による exe ビルド手順
