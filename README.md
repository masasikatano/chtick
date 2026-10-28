# chtick — 中国A株 業種別一覧サイト

上海証券取引所（SSE）・深セン証券取引所（SZSE）上場の A 株（普通株）約5,400銘柄を業種タブ別に一覧表示する静的サイト。Oracle Cloud VM の cron で平日日次自動更新（JST 17:30）し、GitHub Pages で公開する。仕様の詳細は `spec.md`、構成の詳細は `architecture.md`。

## エージェントへの指示

- コード変更後は必ず `.venv/bin/python -m pytest tests/ -q` で全テストを通すこと。
- マスタ取得のフォールバック構成・障害調査手順は `.kimi/skills/` を参照すること。
- 除外コード帯を変える場合は `tests/test_master.py` のパラメータ化テストも更新すること。
- 新規ドキュメント（README 等）の作成は指示がない限り行わないこと。

## ディレクトリ構成

- `src/` — データパイプライン（`master.py` マスタ取得、`eastmoney.py`/`yahoo.py` 価格、`update.py` 集約）
- `tests/` — pytest（フィルタ・終値/前日比計算・スキーマ・UTF-8）
- `docs/` — GitHub Pages の公開資産（`index.html` / `common.js` / `data/latest.json`）
- `data/master.json` — 銘柄マスタのフォールバックスナップショット（取得全経路失敗時の最終防衛線）
- `.github/workflows/update.yml` — 平日日次更新ワークフロー
- `.kimi/` — Kimi Code CLI 用のコマンド・スキール・設定（`.claude/` `.agents/` から symlink）

## ローカル開発

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q   # テスト
./run_local.sh                         # ローカルプレビュー（取得→:8080 で配信）
./run_local.sh --serve-only            # 既存 latest.json を配信するだけ（再取得しない）
.venv/bin/python -m src.update         # データ更新（latest.json 生成）
```

## データソース

| 用途 | 優先 | フォールバック |
| --- | --- | --- |
| 銘柄マスタ | EastMoney clist | 取引所公式（SSE suggest / cninfo・SZSE レポート）→ ulist プローブ → `data/master.json` |
| 価格 | EastMoney quote API（100銘柄/回） | Yahoo Finance chart API（`.SS`/`.SZ`） |

前日比・終値はいずれのソースでも close の最後の2点から自前計算する。API キーは不要。
