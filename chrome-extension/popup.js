"use strict";

const API_URL = "http://127.0.0.1:18765/api/extension/status";
const DASHBOARD_URL = "http://127.0.0.1:18765/";
const $ = (id) => document.getElementById(id);
let refreshing = false;

function number(value, digits = 1) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "--";
}

function time(value) {
  if (!value) return "尚未更新";
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function diskTone(free, threshold, target) {
  if (free < threshold) return "danger";
  if (free < target) return "watch";
  return "safe";
}

function render(payload) {
  const { automatic_cleanup: automaticCleanup, disk, guard, resources } = payload;
  const tone = diskTone(disk.free_gib, guard.threshold_gib, guard.target_gib);
  $("disk-free").textContent = number(disk.free_gib, 1);
  $("disk-used").textContent = `${number(disk.used_percent, 1)}% 已用`;
  $("disk-label").textContent =
    tone === "danger" ? "清理触发" : tone === "watch" ? "持续观察" : "空间安全";
  $("disk-meter").style.width = `${Math.max(0, Math.min(100, disk.free_percent))}%`;
  $("disk-meter").className = tone === "safe" ? "" : tone;

  const system = resources.system;
  $("cpu-value").textContent = `${number(system.cpu_percent, 0)}%`;
  $("cpu-state").textContent = `Load ${system.load_average.map((v) => number(v, 1)).join(" / ")}`;
  $("memory-value").textContent = `${number(system.memory_used_percent, 0)}%`;
  $("memory-state").textContent = `${number(system.memory_available_gib, 1)} GiB 可用`;
  $("swap-value").textContent = `${number(system.swap_percent, 0)}%`;
  $("swap-state").textContent = `${number(system.swap_used_gib, 1)} GiB 已用`;

  const cleanupEnabled = Boolean(automaticCleanup?.enabled);
  const cleanupHealthy = Boolean(automaticCleanup?.healthy);
  const cleanupRunning = Boolean(automaticCleanup?.running);
  const cleanupPressure = Boolean(automaticCleanup?.pressure_active);
  $("guard-dot").className = `status-dot ${cleanupHealthy ? "safe" : "danger"}`;
  $("guard-title").textContent = cleanupRunning
    ? "自动清理正在运行"
    : cleanupPressure
      ? "自动清理处于压力态"
      : cleanupEnabled
        ? "自动清理已启用"
        : "自动清理未启用";
  $("guard-detail").textContent = cleanupEnabled
    ? `低于 ${automaticCleanup.trigger_free_gib} GiB 触发 · 恢复到 ${automaticCleanup.target_free_gib} GiB`
    : "请安装或重新运行本机 Companion 安装器";
  $("cleanup-state").textContent = cleanupRunning
    ? "运行中"
    : cleanupEnabled
      ? "ON"
      : "OFF";

  const list = $("process-list");
  list.replaceChildren();
  (resources.processes.cpu || []).slice(0, 3).forEach((item) => {
    const row = document.createElement("div");
    row.className = "process-row";
    const name = document.createElement("strong");
    name.textContent = item.name || "未知进程";
    name.title = `PID ${item.pid}`;
    const value = document.createElement("span");
    value.textContent = `${number(item.cpu_percent, 1)}%`;
    row.append(name, value);
    list.append(row);
  });
  $("connection-state").textContent = "已连接";
  $("connection-state").className = "connection online";
  $("updated-at").textContent = `更新 ${time(payload.timestamp)}`;
  $("offline-panel").hidden = true;
  chrome.storage.local.set({ lastStatus: payload, lastStatusAt: Date.now(), lastError: null });
}

function showOffline() {
  $("connection-state").textContent = "未连接";
  $("connection-state").className = "connection offline";
  $("offline-panel").hidden = false;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  $("refresh-button").disabled = true;
  try {
    const response = await fetch(API_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
    chrome.runtime.sendMessage({ type: "refreshStatus" });
  } catch (error) {
    const cached = await chrome.storage.local.get(["lastStatus"]);
    if (cached.lastStatus) render(cached.lastStatus);
    showOffline();
  } finally {
    refreshing = false;
    $("refresh-button").disabled = false;
  }
}

$("refresh-button").addEventListener("click", refresh);
$("offline-retry").addEventListener("click", refresh);
$("dashboard-button").addEventListener("click", () => {
  chrome.tabs.create({ url: DASHBOARD_URL });
});

refresh();
