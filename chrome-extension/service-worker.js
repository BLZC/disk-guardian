"use strict";

const API_URL = "http://127.0.0.1:18765/api/extension/status";
const DASHBOARD_URL = "http://127.0.0.1:18765/";
const ALARM_NAME = "disk-guardian-status-refresh";

function badgeState(payload) {
  const free = payload?.disk?.free_gib;
  const threshold = payload?.guard?.threshold_gib ?? 10;
  const target = payload?.guard?.target_gib ?? 20;
  if (!Number.isFinite(free)) {
    return { text: "!", color: "#ff726f", title: "本机守护服务未连接" };
  }
  if (!payload?.automatic_cleanup?.enabled) {
    return { text: "!", color: "#ff726f", title: "自动清理未启用" };
  }
  if (!payload?.automatic_cleanup?.healthy) {
    return { text: "!", color: "#ff726f", title: "自动清理需要检查" };
  }
  if (free < threshold) {
    return { text: `${Math.max(0, Math.round(free))}`, color: "#ff726f", title: `磁盘压力：剩余 ${free.toFixed(1)} GiB` };
  }
  if (free < target) {
    return { text: `${Math.round(free)}`, color: "#ffca67", title: `磁盘观察：剩余 ${free.toFixed(1)} GiB` };
  }
  return { text: "", color: "#48e8ae", title: `磁盘安全：剩余 ${free.toFixed(1)} GiB` };
}

async function updateBadge() {
  try {
    const response = await fetch(API_URL, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const state = badgeState(payload);
    await chrome.action.setBadgeBackgroundColor({ color: state.color });
    await chrome.action.setBadgeText({ text: state.text });
    await chrome.action.setTitle({ title: state.title });
    await chrome.storage.local.set({
      lastStatus: payload,
      lastStatusAt: Date.now(),
      lastError: null,
    });
  } catch (error) {
    await chrome.action.setBadgeBackgroundColor({ color: "#ff726f" });
    await chrome.action.setBadgeText({ text: "!" });
    await chrome.action.setTitle({ title: "磁盘守望台：本机服务未连接" });
    await chrome.storage.local.set({
      lastError: String(error),
      lastErrorAt: Date.now(),
    });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  updateBadge();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM_NAME, { periodInMinutes: 1 });
  updateBadge();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) updateBadge();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "refreshStatus") {
    updateBadge().then(
      () => sendResponse({ ok: true }),
      (error) => sendResponse({ ok: false, error: String(error) }),
    );
    return true;
  }
  if (message?.type === "openDashboard") {
    chrome.tabs.create({ url: DASHBOARD_URL });
    sendResponse({ ok: true });
  }
  return false;
});

updateBadge();
