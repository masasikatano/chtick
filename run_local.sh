#!/usr/bin/env bash
# 手元で 中国上場（A株）個別株一覧データを更新し、docs/ を簡易サーバで開く。
#
#   ./run_local.sh              # venv → 取得 → :8080 で配信
#   ./run_local.sh --no-serve   # JSON の更新だけ
#   ./run_local.sh --serve-only # 既存 latest.json を配信するだけ
#   PORT=9000 ./run_local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8080}"
DO_UPDATE=1
DO_SERVE=1

for arg in "$@"; do
  case "$arg" in
    --no-serve) DO_SERVE=0 ;;
    --serve-only) DO_UPDATE=0 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      echo "usage: $0 [--no-serve|--serve-only]" >&2
      exit 2
      ;;
  esac
done

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  else
    PYTHON=python
  fi
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "python3 が見つかりません" >&2
  exit 1
fi

VENV="$ROOT/.venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "==> venv を作成: $VENV"
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

if [[ "$DO_UPDATE" -eq 1 ]]; then
  echo "==> 依存関係を入れる"
  pip install -q -r "$ROOT/requirements.txt"
  echo "==> EastMoney 銘柄マスタ / quote API（Yahoo Finance フォールバック）から取得して docs/data/latest.json を更新"
  python -m src.update
fi

if [[ "$DO_SERVE" -eq 0 ]]; then
  echo "JSON 更新のみ終了。配信する場合は $0 --serve-only"
  exit 0
fi

echo "==> http://127.0.0.1:${PORT}/  （Ctrl+C で停止）"
exec python -m http.server "$PORT" -d "$ROOT/docs"
