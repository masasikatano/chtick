---
name: daily-update-check
description: GitHub Actions の update ワークフロー失敗時の調査手順。スケジュール更新が止まった・最新の価格が反映されない場合に使う。
---

# 日次更新（update ワークフロー）の障害調査

## ワークフローの構造

`.github/workflows/update.yml`：平日 09:30 UTC（JST 18:30）に `python -m src.update` を実行し、
`docs/data/latest.json` と `data/master.json` を `[skip ci]` 付きで main に push する。

## 調査手順

1. 失敗した run のログで `python -m src.update` ステップの末尾を見る。
   - `FileNotFoundError: data/master.json` → skill `master-data-sources` を参照（スナップショット未コミット or 全経路失敗）。
   - 502 が出ていても取引所公式経路（`取引所公式一覧利用:` のログ）にフォールバックしていればマスタ取得は成功。
2. コミットステップで落ちている場合 → `git add` 失敗か push 失敗（permissions / ブランチ保護）を確認。
3. 「成功しているが latest.json が古い」→ push はされたがサイトが更新されていない。
   GitHub Pages（branch `main` の `/docs`）のデプロイ状況を確認。

## よくある落とし穴

- `data/master.json` は初回の成功実行でしか生成されない。コミットステップはファイル未生成でも
  失敗しないよう `|| echo` ガード済みだが、その場合スナップショットはリポジトリに無いまま。
  **ローカルで生成してコミットしておくことで全経路ダウン時の最終防衛線になる。**
- 中国の長期連休（春節・国慶節）は市場が休み、価格の `as_of` が直近営業日のままになる。
  これは障害ではなく仕様（免責表現でカバー済み）。

## 修正後の確認

- ローカルで `.venv/bin/python -m src.update` が通ること。
- `gh run list --workflow update.yml` で次回 run が成功すること（または `workflow_dispatch` で即実行）。
