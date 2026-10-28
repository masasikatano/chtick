#!/bin/bash
# Oracle Cloud VM の cron から定期実行される更新スクリプト。
# crontab 例: 30 17 * * 1-5 ~/chtick/run_update.sh >> ~/chtick/update.log 2>&1
set -e
cd "$(dirname "$0")"

git fetch origin && git reset --hard origin/main   # リポジトリ最新化

.venv/bin/python -m src.update

git add docs/data/latest.json
git add data/master.json 2>/dev/null || echo "data/master.json は未生成"
if git diff --cached --quiet; then
  echo "no changes"
  exit 0
fi
git -c user.name="oracle-cron" -c user.email="oracle-cron@users.noreply.github.com" \
    commit -m "chore: update latest.json [skip ci]"
git push origin main
