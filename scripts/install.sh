#!/bin/bash
set -euo pipefail

PRODUCT_NAME="Disk Guardian"
PRODUCT_SLUG="disk-guardian"
PRODUCT_VERSION="0.2.1"
LABEL_PREFIX="io.github.blzc.disk-guardian"
DEFAULT_EXTENSION_ID="ccpomkognonnccbjmiapheoadpnepnde"
STORE_EXTENSION_ID="knfhjpciofoakljbmneaaailglnmamlk"
PSUTIL_VERSION="7.2.2"
PORT=18765

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_ROOT="${DISK_GUARDIAN_INSTALL_DIR:-$HOME/.local/share/$PRODUCT_SLUG}"
STATE_DIR="${DISK_GUARDIAN_STATE_DIR:-$HOME/Library/Application Support/$PRODUCT_NAME}"
LOG_DIR="${DISK_GUARDIAN_LOG_DIR:-$HOME/Library/Logs/$PRODUCT_NAME}"
LAUNCH_AGENT_DIR="${DISK_GUARDIAN_LAUNCH_AGENT_DIR:-$HOME/Library/LaunchAgents}"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"

EXTENSION_ID=""
THRESHOLD_GIB=""
TARGET_GIB=""
LOAD_AGENTS=1

usage() {
  cat <<'EOF'
用法：./scripts/install.sh [选项]

安装或升级 Disk Guardian 本机 Companion，并默认启用自动清理。

选项：
  --extension-id ID   允许访问 Companion 的 Chrome 扩展 ID
  --threshold-gib N   剩余空间低于 N GiB 时触发（默认 20）
  --target-gib N      清理到 N GiB 后停止（默认 30）
  --no-load           只写入文件，不加载 LaunchAgent
  -h, --help          显示帮助

首次安装会创建独立 Python venv，并从 PyPI 安装 psutil 的二进制 wheel。
EOF
}

fail() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

positive_integer() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) test "$1" -gt 0 ;;
  esac
}

valid_extension_id() {
  case "$1" in
    *[!a-p]*|'') return 1 ;;
    *) test "${#1}" -eq 32 ;;
  esac
}

while test "$#" -gt 0; do
  case "$1" in
    --extension-id)
      test "$#" -ge 2 || fail "--extension-id 缺少值"
      EXTENSION_ID="$2"
      shift 2
      ;;
    --threshold-gib)
      test "$#" -ge 2 || fail "--threshold-gib 缺少值"
      THRESHOLD_GIB="$2"
      shift 2
      ;;
    --target-gib)
      test "$#" -ge 2 || fail "--target-gib 缺少值"
      TARGET_GIB="$2"
      shift 2
      ;;
    --no-load)
      LOAD_AGENTS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "未知选项：$1"
      ;;
  esac
done

test "$(uname -s)" = "Darwin" || fail "当前版本只支持 macOS"
PYTHON_BIN="${DISK_GUARDIAN_PYTHON:-$(command -v python3 || true)}"
test -n "$PYTHON_BIN" || fail "未找到 Python 3"
"$PYTHON_BIN" -c \
  'import sys; raise SystemExit(sys.version_info < (3, 9))' ||
  fail "需要 Python 3.9 或更高版本"

CONFIG_PATH="$INSTALL_ROOT/install.json"
if test -f "$CONFIG_PATH"; then
  while IFS='=' read -r key value; do
    case "$key" in
      extension_id)
        test -n "$EXTENSION_ID" || EXTENSION_ID="$value"
        ;;
      threshold_gib)
        test -n "$THRESHOLD_GIB" || THRESHOLD_GIB="$value"
        ;;
      target_gib)
        test -n "$TARGET_GIB" || TARGET_GIB="$value"
        ;;
    esac
  done < <(
    "$PYTHON_BIN" - "$CONFIG_PATH" <<'PY' 2>/dev/null || true
import json
import sys

try:
    value = json.load(open(sys.argv[1]))
except (OSError, json.JSONDecodeError):
    value = {}
for key in ("extension_id", "threshold_gib", "target_gib"):
    item = value.get(key)
    if isinstance(item, (str, int)):
        print(f"{key}={item}")
PY
  )
fi

EXTENSION_ID="${EXTENSION_ID:-$DEFAULT_EXTENSION_ID}"
THRESHOLD_GIB="${THRESHOLD_GIB:-20}"
TARGET_GIB="${TARGET_GIB:-30}"

valid_extension_id "$EXTENSION_ID" ||
  fail "Chrome 扩展 ID 必须是 32 位 a-p 字符串"
positive_integer "$THRESHOLD_GIB" ||
  fail "threshold 必须是正整数"
positive_integer "$TARGET_GIB" ||
  fail "target 必须是正整数"
test "$TARGET_GIB" -gt "$THRESHOLD_GIB" ||
  fail "target 必须大于 threshold"

for required in \
  server.py system_metrics.py cleanup.py cleanup_policy.py requirements.txt \
  companion/disk_guard.py companion/resource_guard.py \
  dist/index.html dist/app.js dist/styles.css; do
  test -f "$SOURCE_DIR/$required" ||
    fail "安装包不完整：缺少 $required"
done

SOURCE_DIGEST="$(
  cd "$SOURCE_DIR"
  shasum -a 256 \
    server.py \
    system_metrics.py \
    cleanup.py \
    cleanup_policy.py \
    requirements.txt \
    companion/disk_guard.py \
    companion/resource_guard.py \
    dist/index.html \
    dist/app.js \
    dist/styles.css |
    shasum -a 256 |
    awk '{print $1}'
)"
RELEASE_ID="$PRODUCT_VERSION-$(printf '%s' "$SOURCE_DIGEST" | cut -c1-12)"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"

validate_product_directory() {
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
  )" || fail "不安全的产品目录：$path"
  if test -L "$path"; then
    fail "产品目录不能是符号链接：$path"
  fi
  if test -e "$path" && ! test -d "$path"; then
    fail "产品目录路径已被非目录占用：$path"
  fi
  if test -d "$path"; then
    if test -f "$path/$marker_name"; then
      test "$(cat "$path/$marker_name" 2>/dev/null || true)" = \
        "$PRODUCT_SLUG" ||
        fail "产品目录标记无效：$path"
    elif find "$path" -mindepth 1 -maxdepth 1 -print -quit |
      grep -q .; then
      fail "目录已存在且不属于 Disk Guardian：$path"
    fi
  fi
  printf '%s\n' "$canonical"
}

INSTALL_ROOT="$(validate_product_directory "$INSTALL_ROOT" ".disk-guardian-install")"
STATE_DIR="$(validate_product_directory "$STATE_DIR" ".disk-guardian-state")"
LOG_DIR="$(validate_product_directory "$LOG_DIR" ".disk-guardian-logs")"
if test "$INSTALL_ROOT" = "$STATE_DIR" ||
  test "$INSTALL_ROOT" = "$LOG_DIR" ||
  test "$STATE_DIR" = "$LOG_DIR"; then
  fail "安装、状态和日志目录必须互不相同"
fi
case "$STATE_DIR/" in
  "$INSTALL_ROOT/"*|"$LOG_DIR/"*) fail "状态目录不能嵌套在其他产品目录中" ;;
esac
case "$LOG_DIR/" in
  "$INSTALL_ROOT/"*|"$STATE_DIR/"*) fail "日志目录不能嵌套在其他产品目录中" ;;
esac
case "$INSTALL_ROOT/" in
  "$STATE_DIR/"*|"$LOG_DIR/"*) fail "安装目录不能嵌套在其他产品目录中" ;;
esac
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"
CONFIG_PATH="$INSTALL_ROOT/install.json"

mkdir -p \
  "$INSTALL_ROOT" "$RELEASES_DIR" \
  "$STATE_DIR" "$LOG_DIR" "$LAUNCH_AGENT_DIR"
chmod 700 "$INSTALL_ROOT" "$STATE_DIR" "$LOG_DIR"
printf '%s\n' "$PRODUCT_SLUG" >"$INSTALL_ROOT/.disk-guardian-install"
printf '%s\n' "$PRODUCT_SLUG" >"$STATE_DIR/.disk-guardian-state"
printf '%s\n' "$PRODUCT_SLUG" >"$LOG_DIR/.disk-guardian-logs"
chmod 600 \
  "$INSTALL_ROOT/.disk-guardian-install" \
  "$STATE_DIR/.disk-guardian-state" \
  "$LOG_DIR/.disk-guardian-logs"

release_is_valid() {
  candidate="$1"
  candidate_python="$candidate/venv/bin/python"
  test -x "$candidate_python" || return 1
  for required in \
    server.py system_metrics.py cleanup.py cleanup_policy.py requirements.txt \
    companion/disk_guard.py companion/resource_guard.py \
    dist/index.html dist/app.js dist/styles.css; do
    test -f "$candidate/$required" || return 1
    cmp -s "$SOURCE_DIR/$required" "$candidate/$required" || return 1
  done
  "$candidate_python" -c \
    "import psutil; raise SystemExit(psutil.__version__ != '$PSUTIL_VERSION')" \
    >/dev/null 2>&1 || return 1
  "$candidate_python" -m py_compile \
    "$candidate/server.py" \
    "$candidate/system_metrics.py" \
    "$candidate/cleanup.py" \
    "$candidate/cleanup_policy.py" \
    "$candidate/companion/disk_guard.py" \
    "$candidate/companion/resource_guard.py" \
    >/dev/null 2>&1
}

if ! release_is_valid "$RELEASE_DIR"; then
  if test -e "$RELEASE_DIR"; then
    RELEASE_ID="$RELEASE_ID-$(date +%s)-$$"
    RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"
  fi
  STAGE_DIR="$(mktemp -d "$RELEASES_DIR/.${RELEASE_ID}.stage.XXXXXX")"
  cleanup_stage() {
    if test -n "${STAGE_DIR:-}" && test -d "$STAGE_DIR"; then
      rm -rf "$STAGE_DIR"
    fi
  }
  trap cleanup_stage EXIT

  mkdir -p "$STAGE_DIR/companion" "$STAGE_DIR/dist"
  install -m 644 "$SOURCE_DIR/server.py" "$STAGE_DIR/server.py"
  install -m 644 \
    "$SOURCE_DIR/system_metrics.py" \
    "$STAGE_DIR/system_metrics.py"
  install -m 644 "$SOURCE_DIR/cleanup.py" "$STAGE_DIR/cleanup.py"
  install -m 644 \
    "$SOURCE_DIR/cleanup_policy.py" \
    "$STAGE_DIR/cleanup_policy.py"
  install -m 644 \
    "$SOURCE_DIR/requirements.txt" \
    "$STAGE_DIR/requirements.txt"
  install -m 755 \
    "$SOURCE_DIR/companion/disk_guard.py" \
    "$STAGE_DIR/companion/disk_guard.py"
  install -m 755 \
    "$SOURCE_DIR/companion/resource_guard.py" \
    "$STAGE_DIR/companion/resource_guard.py"
  cp -R "$SOURCE_DIR/dist/." "$STAGE_DIR/dist/"
  find "$STAGE_DIR/dist" -type f -exec chmod 644 {} \;

  "$PYTHON_BIN" -m venv "$STAGE_DIR/venv"
  "$STAGE_DIR/venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-input \
    --only-binary=:all: \
    --require-hashes \
    --requirement "$STAGE_DIR/requirements.txt"
  "$STAGE_DIR/venv/bin/python" -m py_compile \
    "$STAGE_DIR/server.py" \
    "$STAGE_DIR/system_metrics.py" \
    "$STAGE_DIR/cleanup.py" \
    "$STAGE_DIR/cleanup_policy.py" \
    "$STAGE_DIR/companion/disk_guard.py" \
    "$STAGE_DIR/companion/resource_guard.py"
  "$STAGE_DIR/venv/bin/python" -c \
    "import psutil; raise SystemExit(psutil.__version__ != '$PSUTIL_VERSION')"

  mv "$STAGE_DIR" "$RELEASE_DIR"
  STAGE_DIR=""
  trap - EXIT
fi

if test -e "$CURRENT_LINK" && ! test -L "$CURRENT_LINK"; then
  fail "current 路径不是符号链接：$CURRENT_LINK"
fi
"$RELEASE_DIR/venv/bin/python" \
  "$RELEASE_DIR/companion/disk_guard.py" --status >/dev/null
"$RELEASE_DIR/venv/bin/python" \
  "$RELEASE_DIR/companion/resource_guard.py" --status >/dev/null

DISK_LABEL="$LABEL_PREFIX.disk-guard"
RESOURCE_LABEL="$LABEL_PREFIX.resource-guard"
DASHBOARD_LABEL="$LABEL_PREFIX.dashboard"
DISK_PLIST="$LAUNCH_AGENT_DIR/$DISK_LABEL.plist"
RESOURCE_PLIST="$LAUNCH_AGENT_DIR/$RESOURCE_LABEL.plist"
DASHBOARD_PLIST="$LAUNCH_AGENT_DIR/$DASHBOARD_LABEL.plist"
DISK_PLIST_NEXT="$INSTALL_ROOT/.disk-guard.plist.next"
RESOURCE_PLIST_NEXT="$INSTALL_ROOT/.resource-guard.plist.next"
DASHBOARD_PLIST_NEXT="$INSTALL_ROOT/.dashboard.plist.next"

EXTENSION_IDS="$EXTENSION_ID"
if test "$EXTENSION_ID" != "$STORE_EXTENSION_ID"; then
  EXTENSION_IDS="$EXTENSION_IDS,$STORE_EXTENSION_ID"
fi
export RELEASE_DIR STATE_DIR LOG_DIR EXTENSION_ID EXTENSION_IDS
export THRESHOLD_GIB TARGET_GIB
export PORT DISK_LABEL RESOURCE_LABEL DASHBOARD_LABEL
export DISK_PLIST_NEXT RESOURCE_PLIST_NEXT DASHBOARD_PLIST_NEXT
"$PYTHON_BIN" <<'PY'
import os
import plistlib
from pathlib import Path

release = Path(os.environ["RELEASE_DIR"])
state_dir = os.environ["STATE_DIR"]
log_dir = Path(os.environ["LOG_DIR"])
python = str(release / "venv/bin/python")
common = {
    "DISK_GUARDIAN_STATE_DIR": state_dir,
    "DISK_GUARDIAN_DISK_LABEL": os.environ["DISK_LABEL"],
    "DISK_GUARDIAN_RESOURCE_LABEL": os.environ["RESOURCE_LABEL"],
}
disk_env = {
    **common,
    "DISK_GUARDIAN_THRESHOLD_GIB": os.environ["THRESHOLD_GIB"],
    "DISK_GUARDIAN_TARGET_GIB": os.environ["TARGET_GIB"],
    "DISK_GUARDIAN_MIN_AGE_SECONDS": "3600",
    "DISK_GUARDIAN_CACHE_QUIET_SECONDS": "300",
    "DISK_GUARDIAN_HEALTHY_HEARTBEAT_SECONDS": "3600",
}
resource_env = {
    **common,
    "DISK_GUARDIAN_CPU_THRESHOLD_PERCENT": "200",
    "DISK_GUARDIAN_MEMORY_THRESHOLD_GIB": "4",
    "DISK_GUARDIAN_CPU_STREAK_REQUIRED": "5",
    "DISK_GUARDIAN_MEMORY_STREAK_REQUIRED": "3",
    "DISK_GUARDIAN_MIN_RUNTIME_SECONDS": "1800",
    "DISK_GUARDIAN_MAX_RUNTIME_SECONDS": "7200",
    "DISK_GUARDIAN_ORPHAN_RUNTIME_SECONDS": "1800",
    "DISK_GUARDIAN_MEMORY_AVAILABLE_PERCENT": "12",
    "DISK_GUARDIAN_SWAP_PRESSURE_GIB": "5",
    "DISK_GUARDIAN_TERM_GRACE_SECONDS": "120",
}
dashboard_env = {
    **common,
    "DISK_GUARDIAN_PORT": os.environ["PORT"],
    "DISK_GUARDIAN_EXTENSION_ORIGINS": ",".join(
        "chrome-extension://" + extension_id
        for extension_id in os.environ["EXTENSION_IDS"].split(",")
    ),
    "PYTHONUNBUFFERED": "1",
}
definitions = [
    (
        os.environ["DISK_PLIST_NEXT"],
        {
            "Label": os.environ["DISK_LABEL"],
            "ProgramArguments": [
                python,
                str(release / "companion/disk_guard.py"),
            ],
            "EnvironmentVariables": disk_env,
            "RunAtLoad": True,
            "StartInterval": 60,
            "ProcessType": "Background",
            "StandardOutPath": str(log_dir / "disk-guard.log"),
            "StandardErrorPath": str(log_dir / "disk-guard.err.log"),
        },
    ),
    (
        os.environ["RESOURCE_PLIST_NEXT"],
        {
            "Label": os.environ["RESOURCE_LABEL"],
            "ProgramArguments": [
                python,
                str(release / "companion/resource_guard.py"),
            ],
            "EnvironmentVariables": resource_env,
            "RunAtLoad": True,
            "StartInterval": 60,
            "ProcessType": "Background",
            "StandardOutPath": str(log_dir / "resource-guard.log"),
            "StandardErrorPath": str(log_dir / "resource-guard.err.log"),
        },
    ),
    (
        os.environ["DASHBOARD_PLIST_NEXT"],
        {
            "Label": os.environ["DASHBOARD_LABEL"],
            "ProgramArguments": [
                python,
                str(release / "server.py"),
            ],
            "EnvironmentVariables": dashboard_env,
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
            "ProcessType": "Background",
            "StandardOutPath": str(log_dir / "dashboard.log"),
            "StandardErrorPath": str(log_dir / "dashboard.err.log"),
        },
    ),
]
for destination, value in definitions:
    path = Path(destination)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(value, handle, sort_keys=True)
    temporary.chmod(0o644)
    temporary.replace(path)
PY

for plist in \
  "$DISK_PLIST_NEXT" "$RESOURCE_PLIST_NEXT" "$DASHBOARD_PLIST_NEXT"; do
  plutil -lint "$plist" >/dev/null
done

NEXT_LINK="$INSTALL_ROOT/.current.next"
rm -f "$NEXT_LINK"
ln -s "releases/$RELEASE_ID" "$NEXT_LINK"
NEXT_CONFIG="$INSTALL_ROOT/.install.json.next"
cat >"$NEXT_CONFIG" <<EOF
{
  "product": "$PRODUCT_SLUG",
  "version": "$PRODUCT_VERSION",
  "release_id": "$RELEASE_ID",
  "extension_id": "$EXTENSION_ID",
  "threshold_gib": $THRESHOLD_GIB,
  "target_gib": $TARGET_GIB,
  "port": $PORT
}
EOF
chmod 600 "$NEXT_CONFIG"

if test "$LOAD_AGENTS" -eq 1; then
  DOMAIN="gui/$(id -u)"
  BACKUP_DIR="$(mktemp -d "$INSTALL_ROOT/.launchd-backup.XXXXXX")"
  for plist in "$DISK_PLIST" "$RESOURCE_PLIST" "$DASHBOARD_PLIST"; do
    if test -f "$plist"; then
      cp "$plist" "$BACKUP_DIR/$(basename "$plist")"
    fi
  done
  for label in "$DASHBOARD_LABEL" "$DISK_LABEL" "$RESOURCE_LABEL"; do
    launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  done
  loaded_labels=()
  rollback_launch_agents() {
    for label in "${loaded_labels[@]}"; do
      launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
    done
    for plist in "$DISK_PLIST" "$RESOURCE_PLIST" "$DASHBOARD_PLIST"; do
      backup="$BACKUP_DIR/$(basename "$plist")"
      if test -f "$backup"; then
        cp "$backup" "$plist"
        launchctl bootstrap "$DOMAIN" "$plist" >/dev/null 2>&1 || true
      else
        rm -f "$plist"
      fi
    done
    rm -f "$NEXT_LINK" "$NEXT_CONFIG"
    rm -rf "$BACKUP_DIR"
  }
  trap rollback_launch_agents ERR
  mv -f "$DISK_PLIST_NEXT" "$DISK_PLIST"
  mv -f "$RESOURCE_PLIST_NEXT" "$RESOURCE_PLIST"
  mv -f "$DASHBOARD_PLIST_NEXT" "$DASHBOARD_PLIST"
  launchctl bootstrap "$DOMAIN" "$DISK_PLIST"
  loaded_labels+=("$DISK_LABEL")
  launchctl bootstrap "$DOMAIN" "$RESOURCE_PLIST"
  loaded_labels+=("$RESOURCE_LABEL")
  launchctl bootstrap "$DOMAIN" "$DASHBOARD_PLIST"
  loaded_labels+=("$DASHBOARD_LABEL")
  launchctl enable "$DOMAIN/$DISK_LABEL"
  launchctl enable "$DOMAIN/$RESOURCE_LABEL"
  launchctl enable "$DOMAIN/$DASHBOARD_LABEL"
  launchctl kickstart -k "$DOMAIN/$DASHBOARD_LABEL"
  "$RELEASE_DIR/venv/bin/python" - <<'PY'
import json
import time
import urllib.request

url = "http://127.0.0.1:18765/api/extension/status"
last_error = None
for _ in range(20):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            payload = json.load(response)
        if payload.get("product") != "disk-guardian":
            raise RuntimeError("unexpected Companion response")
        break
    except Exception as error:
        last_error = error
        time.sleep(0.5)
else:
    raise SystemExit(f"Companion health check failed: {last_error}")
PY
  "$PYTHON_BIN" - "$NEXT_LINK" "$CURRENT_LINK" <<'PY'
import os
import sys

os.replace(sys.argv[1], sys.argv[2])
PY
  mv -f "$NEXT_CONFIG" "$CONFIG_PATH"
  rm -rf "$BACKUP_DIR"
  trap - ERR
else
  mv -f "$DISK_PLIST_NEXT" "$DISK_PLIST"
  mv -f "$RESOURCE_PLIST_NEXT" "$RESOURCE_PLIST"
  mv -f "$DASHBOARD_PLIST_NEXT" "$DASHBOARD_PLIST"
  "$PYTHON_BIN" - "$NEXT_LINK" "$CURRENT_LINK" <<'PY'
import os
import sys

os.replace(sys.argv[1], sys.argv[2])
PY
  mv -f "$NEXT_CONFIG" "$CONFIG_PATH"
fi

printf '\n%s %s 已安装。\n' "$PRODUCT_NAME" "$PRODUCT_VERSION"
printf '自动清理：低于 %s GiB 触发，恢复到 %s GiB 后停止。\n' \
  "$THRESHOLD_GIB" "$TARGET_GIB"
printf '仪表盘：http://127.0.0.1:%s/\n' "$PORT"
printf '日志：%s\n' "$LOG_DIR"
if test "$LOAD_AGENTS" -eq 0; then
  printf 'LaunchAgent 未加载（--no-load）。\n'
else
  printf '运行 ./scripts/status.sh 检查完整状态。\n'
fi
