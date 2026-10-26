---
name: master-data-sources
description: 銘柄マスタの取得失敗を調査・修正する。EastMoney 502、FileNotFoundError data/master.json、フォールバック経路の確認に使う。
---

# 銘柄マスタ取得の調査・修正

## フォールバック構成（src/master.py の load_master）

取得優先順は以下の通り。上から順に試し、成功した時点でスナップショット（`data/master.json`）を差し替える。

1. **EastMoney clist** (`fetch_all`) — `push2.eastmoney.com/api/qt/clist/get` を全ページ取得。
   GitHub Actions 等の海外クラウド IP を WAF で拒否し、502 を返すことがある（本プロジェクトで実際に発生）。
2. **取引所公式** (`fetch_from_exchanges`)
   - SSE: `www.sse.com.cn/js/common/ssesuggestdata.js` を正規表現でパース（上海 A 株 6xxxxx のみ）。
     たまにタイムアウトするのでリトライ 3 回付き。
   - 深セン: 第一候補は巨潮資訊 `www.cninfo.com.cn/new/data/szse_stock.json`（SZSE 系公式。
     `category == "A股"` かつコードが 0/3 始まりのみ。全市場リストなので交易所フィルタ必須）。
     第二候補に SZSE 公式レポート API（`www.szse.cn` は海外 IP を拒否することがある）。
3. **ulist プローブ** (`probe_via_ulist`) — EastMoney のコード総当たり。EastMoney 自体が落ちていると無力。
4. **スナップショット** — `data/master.json`。リポジトリにコミットしておくことが必須（初回生成失敗でコミット漏れがあった）。

## 典型的な障害と対処

- **Actions で `FileNotFoundError: data/master.json`** → 全経路失敗＋スナップショット未コミット。
  ローカルで `python -c "from src import master; master.load_master()"` を実行して
  `data/master.json` を生成し、コミットする。
- **SZSE が `RemoteDisconnected` で全滅** → この環境の IP が `www.szse.cn` に拒否されている。
  cninfo 経路が生きているか確認する（`master._fetch_szse_cninfo()`）。
- **cninfo の銘柄数が SZSE 公式より多い** → cninfo は全市場かつ取引停止銘柄等を含みうる。
  表示に影響しない（価格取得で落ちた銘柄は price=None の行として残る）が、
  大幅な差があったらデータソース側の仕様変更を疑う。

## 修正時の注意

- コード帯フィルタは `is_a_share()` が唯一の基準。除外帯（900/200/8/4/92/15/16/50/58/11/12 始まり）を変えたら
  `tests/test_master.py` のパラメータ化テストも更新する。
- 新しい取得ソースを足す場合は `fetch_from_exchanges()` の合流部分に加え、
  成功時のみスナップショットを差し替える load_master の不変条件を壊さないこと。
- テストは `tests/test_master.py` にモックベースで追加する（実ネットワークに依存させない）。
