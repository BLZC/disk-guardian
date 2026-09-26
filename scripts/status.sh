#!/bin/bash
set -uo pipefail

PRODUCT_NAME="Disk Guardian"
PRODUCT_SLUG="disk-guardian"
LABEL_PREFIX="io.github.blzc.disk-guardian"
INSTALL_DIR="${DISK_GUARDIAN_INSTALL_DIR:-$HOME/.local/share/$PRODUCT_SLUG}"
STATE_DIR="${DISK_GUARDIAN_STATE_DIR:-$HOME/Library/Application Support/$PRODUCT_NAME}"
LOG_DIR="${DISK_GUARDIAN_LOG_DIR:-$HOME/Library/Logs/$PRODUCT_NAME}"
DOMAIN="gui/$(id -u)"
PYTHON_BIN="${DISK_GUARDIAN_PYTHON:-$(command -v python3 || true)}"

PORT=18765

printf '%s 状态\n' "$PRODUCT_NAME"
printf '安装目录：%s\n' "$INSTALL_DIR"
printf '状态目录：%s\n' "$STATE_DIR"
printf '日志目录：%s\n' "$LOG_DIR"
printf '仪表盘：http://127.0.0.1:%s/\n\n' "$PORT"

overall=0
for service in dashboard disk-guard resource-guard; do
  label="$LABEL_PREFIX.$service"
  if output="$(launchctl print "$DOMAIN/$label" 2>&1)"; then
    state="$(printf '%s\n' "$output" | awk -F' = ' '/^[[:space:]]*state = / {print $2; exit}')"
    runs="$(printf '%s\n' "$output" | awk -F' = ' '/^[[:space:]]*runs = / {print $2; exit}')"
    exit_code="$(printf '%s\n' "$output" | awk -F' = ' '/^[[:space:]]*last exit code = / {print $2; exit}')"
    printf '%-15s loaded=yes state=%s runs=%s last_exit=%s\n' \
      "$service" "${state:-unknown}" "${runs:-0}" "${exit_code:-n/a}"
    if test -n "$exit_code" && test "$exit_code" != "0"; then
      overall=1
    fi
  else
    printf '%-15s loaded=no\n' "$service"
    overall=1
  fi
done

printf '\n'
if payload="$(curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/extension/status" 2>/dev/null)"; then
  if test -n "$PYTHON_BIN"; then
    printf '%s\n' "$payload" | "$PYTHON_BIN" -m json.tool
  else
    printf '%s\n' "$payload"
  fi
else
  printf 'Companion API：unreachable\n'
  overall=1
fi

printf '\n错误日志：\n'
found_error=0
for log in "$LOG_DIR"/*.err.log; do
  test -f "$log" || continue
  if test -s "$log"; then
    found_error=1
    printf -- '--- %s\n' "$log"
    tail -n 20 "$log"
  fi
done
if test "$found_error" -eq 0; then
  printf '无非空错误日志。\n'
fi

exit "$overall"
