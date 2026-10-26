# アーキテクチャ

## 概要

上海（SSE）・深セン（SZSE）上場の A 株（普通株）の業種別一覧サイト。
GitHub Actions で平日日次にデータパイプラインを実行し、GitHub Pages（`main` ブランチの `/docs`）に静的公開する。
API キー不要（EastMoney・Yahoo・取引所公式データはすべて匿名アクセス）。

## データフロー

```
[マスタ取得]  src/master.py
  EastMoney clist → 取引所公式（SSE suggest + cninfo/SZSE レポート）→ ulist プローブ → data/master.json スナップショット
        │
        ▼
[価格取得]    src/eastmoney.py（quote API・100銘柄/回・バッチ。失敗銘柄のみ src/yahoo.py の Yahoo chart API でフォールバック）
        │
        ▼
[集約]        src/update.py → docs/data/latest.json（銘柄マスタ＋価格＋セクタータブ集約）
        │
        ▼
[表示]        docs/index.html + docs/common.js（バニラ JS。業種タブ＋7列テーブル。前日比降順→ヘッダソート）
```

## モジュール責務

| ファイル | 責務 |
| --- | --- |
| `src/master.py` | 銘柄マスタ取得・パース・普通株フィルタ（コード帯ベース）。多段フォールバックとスナップショット管理。 |
| `src/eastmoney.py` | quote API のバッチ取得。終値・前日比は close の最後の2点から自前計算。業種・時価総額も取得。 |
| `src/yahoo.py` | フォールバック専用。`.SS`/`.SZ` 接尾辞の Yahoo chart API。終値・前日比も自前計算。 |
| `src/update.py` | オーケストレーションと latest.json スキーマ生成。セクターは銘柄数上位20＋「その他」に集約。 |

## 不変条件

- 対象は普通 A 株のみ（B股/BSE/ETF/LOF/REIT/優先株/転換社債は除外）。判定は `is_a_share()` のみ。
- 表示列は7列固定（ティッカー/銘柄名/取引所/セクター/終値/前日比/出来高）。UI は日本語、銘柄名は簡体字のまま。
- 価格はいずれのソースでも自前計算。免責表現「参考値（CNY, YYYY-MM-DD時点）」を必ず付ける。
- `data/master.json` はリポジトリにコミットしておく（全取得経路ダウン時の最終防衛線）。
- テストは実ネットワークに依存しない（モックベース）。

## 運用

- 更新: 平日 09:30 UTC（JST 18:30）に schedule 実行＋手動 dispatch。成功時 `[skip ci]` で main に push。
- ローカル開発: `run_local.sh`（プレビュー）、`.venv/bin/python -m pytest tests/ -q`（テスト）。
