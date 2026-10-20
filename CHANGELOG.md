# Changelog

このプロジェクトの変更履歴です。
書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

## [0.1.1] - 2026-10-20

### Added

- `plugin.json`（Assist-Chat 用のプラグイン定義）を追加
- 上位ページの本文取得を並列化

### Fixed

- DuckDuckGo の検索結果が 0 件のとき、「検索に失敗しました」ではなく「検索結果がありませんでした」を返すように修正
- CLI の引数エラーでも JSON の結果行と終了コード 1 を返すように修正

## [0.1.0] - 2026-10-19

### Added

- DuckDuckGo（`ddgs`）による Web 検索と、上位 3 件のページ本文の取得
- LLM への要約依頼を標準入出力で行う `llm_request` / `llm_response` プロトコル
- `search` サブコマンドと `--limit`（1〜20 に丸め、既定は 20）
- `--version` オプション
- `unittest` によるテスト（単体テストとサブプロセステスト）
- PyInstaller による exe ビルド手順
