---
description: 銘柄マスタ＋価格データを取得して docs/data/latest.json を更新する
---

データ更新パイプラインをローカルで実行してください。

1. `.venv/bin/python -m src.update` を実行する
2. 取得ログ（どのマスタソースを使ったか、銘柄数、with_price 数）を確認する
3. 成功したら `data/master.json` と `docs/data/latest.json` が更新されることを確認する

EastMoney が 502 等で失敗した場合は、取引所公式（SSE / cninfo）へのフォールバックが
動作しているかをログで確認してください。どの経路でも最終的に latest.json が書ければ成功です。
