#!/bin/bash
set -euo pipefail

PRODUCT_NAME="Disk Guardian"
PRODUCT_SLUG="disk-guardian"
LABEL_PREFIX="io.github.blzc.disk-guardian"
INSTALL_DIR="${DISK_GUARDIAN_INSTALL_DIR:-$HOME/.local/share/$PRODUCT_SLUG}"
STATE_DIR="${DISK_GUARDIAN_STATE_DIR:-$HOME/Library/Application Support/$PRODUCT_NAME}"
LOG_DIR="${DISK_GUARDIAN_LOG_DIR:-$HOME/Library/Logs/$PRODUCT_NAME}"
LAUNCH_AGENT_DIR="${DISK_GUARDIAN_LAUNCH_AGENT_DIR:-$HOME/Library/LaunchAgents}"
PURGE_DATA=0

usage() {
  cat <<'EOF'
用法：./scripts/uninstall.sh [--purge-data]

默认停止后台任务并删除程序、venv 和 LaunchAgent，保留状态与日志。
--purge-data 还会删除 Disk Guardian 自己的状态与日志。

卸载不会删除 Chrome 插件，也不会删除 Go 模块缓存、项目或个人文件。
EOF
}

while test "$#" -gt 0; do
  case "$1" in
    --purge-data)
      PURGE_DATA=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '错误：未知选项：%s\n' "$1" >&2
      exit 1
      ;;
  esac
done

DOMAIN="gui/$(id -u)"
PYTHON_BIN="${DISK_GUARDIAN_PYTHON:-$(command -v python3 || true)}"
test -n "$PYTHON_BIN" || {
  printf '错误：未找到 Python 3，无法安全验证卸载路径\n' >&2
  exit 1
}

validate_deletion_target() {
  path="$1"
  marker_name="$2"
  canonical="$("$PYTHON_BIN" - "$path" <<'PY'
import os
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.is_absolute():
    raise SystemExit(1)
resolved = Path(os.path.realpath(path))
home = Path.home().resolve()
if resolved in {Path("/"), home, Path("/tmp"), Path("/private/tmp")}:
    raise SystemExit(1)
if len(resolved.parts) < 4:
    raise SystemExit(1)
print(resolved)
PY
  )" || {
    printf '错误：拒绝删除不安全的目录：%s\n' "$path" >&2
    exit 1
  }
  if test -L "$path"; then
    printf '错误：拒绝删除符号链接目录：%s\n' "$path" >&2
    exit 1
  fi
  if test -e "$canonical"; then
    if ! test -d "$canonical" ||
      ! test -f "$canonical/$marker_name" ||
      test "$(cat "$canonical/$marker_name" 2>/dev/null || true)" != \
        "$PRODUCT_SLUG"; then
      printf '错误：拒绝删除没有有效产品标记的目录：%s\n' "$canonical" >&2
      exit 1
    fi
  fi
  printf '%s\n' "$canonical"
}

INSTALL_DIR="$(
  validate_deletion_target "$INSTALL_DIR" ".disk-guardian-install"
)"
if test "$PURGE_DATA" -eq 1; then
  STATE_DIR="$(
    validate_deletion_target "$STATE_DIR" ".disk-guardian-state"
  )"
  LOG_DIR="$(
    validate_deletion_target "$LOG_DIR" ".disk-guardian-logs"
  )"
fi

for service in dashboard disk-guard resource-guard; do
  label="$LABEL_PREFIX.$service"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  rm -f "$LAUNCH_AGENT_DIR/$label.plist"
done

rm -rf "$INSTALL_DIR"

if test "$PURGE_DATA" -eq 1; then
  rm -rf "$STATE_DIR" "$LOG_DIR"
  printf '%s 已卸载，产品状态和日志已删除。\n' "$PRODUCT_NAME"
else
  printf '%s 已卸载。状态和日志仍保留：\n' "$PRODUCT_NAME"
  printf '  %s\n  %s\n' "$STATE_DIR" "$LOG_DIR"
fi
