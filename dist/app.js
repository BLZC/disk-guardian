"use strict";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const REFRESH_MS = 3000;
const HISTORY_LIMIT = 300;
const CIRCUMFERENCE = 2 * Math.PI * 94;

const history = [];
let lastPayload = null;
let toastTimer = null;
let processMode = "cpu";
let cleanupPlan = null;
let cleanupSelected = new Set();
let cleanupBusy = false;

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return Number(value).toFixed(digits);
}

function formatSize(value) {
  if (value === null || value === undefined) return "采样中";
  if (value < 0.01) return "<0.01 GiB";
  return `${formatNumber(value, value >= 10 ? 1 : 2)} GiB`;
}

function formatBytes(bytes) {
  if (!Number.isFinite(Number(bytes))) return "--";
  return formatSize(Number(bytes) / 1024 ** 3);
}

function formatTime(value, fallback = "--") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function commandName(command) {
  if (!command) return "未知构建进程";
  if (command.includes("go test")) return "go test";
  if (command.includes("go build")) return "go build";
  if (command.includes("/link ")) return "Go linker";
  if (command.includes("/compile ")) return "Go compiler";
  if (command.includes("dsymutil")) return "Debug symbols";
  if (command.includes("clang")) return "Clang";
  return command.split(/\s+/).slice(0, 2).join(" ");
}

function setPill(element, label, tone) {
  element.textContent = label;
  element.className = `state-pill ${tone}`;
}

function diskTone(free, threshold, target) {
  if (free < threshold) return "danger";
  if (free < target) return "watch";
  return "safe";
}

function diskStateLabel(free, threshold, target, pressure) {
  if (pressure || free < threshold) return "清理触发";
  if (free < target) return "持续观察";
  return "空间安全";
}

function positionMarker(element, value, total) {
  const bounded = Math.max(0, Math.min(1, value / total));
  const angle = bounded * 360;
  element.style.transform = `rotate(${angle}deg)`;
}

function updateGauge(payload) {
  const { disk, guard } = payload;
  const freeRatio = Math.max(0, Math.min(1, disk.free_gib / disk.total_gib));
  const tone = diskTone(
    disk.free_gib,
    guard.threshold_gib,
    guard.target_gib,
  );
  const progress = $("gauge-progress");
  progress.style.strokeDasharray = CIRCUMFERENCE;
  progress.style.strokeDashoffset = CIRCUMFERENCE * (1 - freeRatio);
  progress.className.baseVal = `gauge-progress ${tone}`;

  $("free-gib").textContent = formatNumber(disk.free_gib, 1);
  $("used-gib").textContent = `${formatNumber(disk.used_gib, 1)} GiB`;
  $("total-gib").textContent = `${formatNumber(disk.total_gib, 1)} GiB`;
  $("used-percent").textContent = `${formatNumber(disk.used_percent, 1)}%`;
  setPill(
    $("disk-state"),
    diskStateLabel(
      disk.free_gib,
      guard.threshold_gib,
      guard.target_gib,
      guard.pressure_active,
    ),
    tone,
  );

  $("gauge-description").textContent =
    `剩余 ${formatNumber(disk.free_gib, 1)} GiB，` +
    `使用率 ${formatNumber(disk.used_percent, 1)}%`;
  positionMarker($("threshold-marker"), guard.threshold_gib, disk.total_gib);
  positionMarker($("target-marker"), guard.target_gib, disk.total_gib);

  const maxScale = Math.max(guard.target_gib * 2.2, disk.free_gib * 1.05, 40);
  const thresholdPercent = Math.min(100, (guard.threshold_gib / maxScale) * 100);
  const targetPercent = Math.min(100, (guard.target_gib / maxScale) * 100);
  const freePercent = Math.min(100, (disk.free_gib / maxScale) * 100);
  $("danger-zone").style.width = `${thresholdPercent}%`;
  $("recovery-zone").style.left = `${thresholdPercent}%`;
  $("recovery-zone").style.width = `${targetPercent - thresholdPercent}%`;
  $("bar-pin").style.left = `${freePercent}%`;
  $("threshold-label").textContent = `${guard.threshold_gib}G 清理线`;
  $("target-label").textContent = `${guard.target_gib}G 恢复线`;
}

function updateGuard(payload) {
  const { guard, disk } = payload;
  const healthy = guard.loaded && guard.enabled && guard.last_exit_code === 0;
  const tone = guard.pressure_active ? "danger" : healthy ? "safe" : "watch";
  const label = guard.pressure_active
    ? "清理中"
    : healthy
      ? "已启用"
      : "需检查";
  setPill($("guard-state"), label, tone);
  $("guard-runs").textContent = `${guard.runs || 0} 次`;
  $("guard-exit").textContent =
    guard.last_exit_code === null ? "--" : String(guard.last_exit_code);
  $("guard-interval").textContent = `${guard.interval_seconds} 秒`;
  $("pressure-state").textContent = guard.pressure_active ? "压力态" : "健康态";
  $("footer-version").textContent =
    `磁盘守护 · 每 ${guard.interval_seconds} 秒检查`;

  const core = document.querySelector(".guard-core");
  core.classList.toggle("danger", guard.pressure_active);
  if (guard.pressure_active) {
    $("guard-summary-title").textContent = "低空间保护已启动";
    $("guard-summary-copy").textContent =
      `当前 ${formatNumber(disk.free_gib, 1)} GiB，可重建产物正在按安全顺序清理。`;
  } else if (healthy) {
    $("guard-summary-title").textContent = "守护进程运行正常";
    $("guard-summary-copy").textContent =
      `低于 ${guard.threshold_gib} GiB 自动清理，空间恢复到 ${guard.target_gib} GiB 后停止。`;
  } else {
    $("guard-summary-title").textContent = "守护进程需要检查";
    $("guard-summary-copy").textContent =
      "服务未加载、未启用或最近执行返回了错误。";
  }
}

function createBuildItem(item) {
  const row = document.createElement("div");
  row.className = "build-item";

  const spinner = document.createElement("span");
  spinner.className = "build-spinner";
  spinner.setAttribute("aria-hidden", "true");

  const command = document.createElement("div");
  command.className = "build-command";
  const name = document.createElement("strong");
  name.textContent = commandName(item.command);
  name.title = item.command;
  const meta = document.createElement("span");
  meta.textContent = `PID ${item.pid}`;
  command.append(name, meta);

  const elapsed = document.createElement("span");
  elapsed.className = "build-time";
  elapsed.textContent = item.elapsed;

  row.append(spinner, command, elapsed);
  return row;
}

function updateBuilds(payload) {
  const { builds } = payload;
  $("build-count").textContent = String(builds.count);
  const list = $("build-list");
  list.replaceChildren();
  if (!builds.count) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    const icon = document.createElement("span");
    icon.className = "empty-icon";
    const copy = document.createElement("p");
    copy.textContent = "当前没有运行中的 Go 编译或测试";
    empty.append(icon, copy);
    list.append(empty);
    return;
  }
  builds.items.forEach((item) => list.append(createBuildItem(item)));
}

function resourceTone(value, watch, danger) {
  if (value >= danger) return "danger";
  if (value >= watch) return "watch";
  return "safe";
}

function setResourceState(id, label, tone) {
  const element = $(id);
  element.textContent = label;
  element.className = `resource-state ${tone}`;
}

function setMeter(id, value, tone) {
  const element = $(id);
  element.style.width = `${Math.max(0, Math.min(100, value))}%`;
  element.style.setProperty(
    "--meter-color",
    tone === "danger"
      ? "var(--red)"
      : tone === "watch"
        ? "var(--amber)"
        : "var(--mint)",
  );
}

function updateSystemResources(payload) {
  const resources = payload.resources;
  if (!resources) return;
  const system = resources.system;
  const cpuTone = resourceTone(system.cpu_percent, 70, 90);
  const memoryTone = resourceTone(system.memory_used_percent, 75, 90);
  const swapTone = resourceTone(system.swap_percent, 65, 88);
  const guard = resources.guard;
  const guardHealthy =
    guard.loaded && guard.enabled && guard.last_exit_code === 0;
  const guardTone = guard.last_action
    ? "watch"
    : guardHealthy
      ? "safe"
      : "danger";

  $("cpu-percent").textContent = `${formatNumber(system.cpu_percent, 0)}%`;
  $("cpu-cores").textContent = `${system.logical_cpus || "--"} 逻辑核`;
  $("cpu-load").textContent =
    `Load ${system.load_average.map((value) => formatNumber(value, 1)).join(" / ")}`;
  setResourceState(
    "cpu-state",
    cpuTone === "safe" ? "正常" : cpuTone === "watch" ? "繁忙" : "高压",
    cpuTone,
  );
  setMeter("cpu-meter", system.cpu_percent, cpuTone);

  $("memory-percent").textContent =
    `${formatNumber(system.memory_used_percent, 0)}%`;
  $("memory-available").textContent =
    `${formatNumber(system.memory_available_gib, 1)} GiB 可用`;
  $("memory-detail").textContent =
    `${formatNumber(system.memory_used_gib, 1)} / ${formatNumber(system.memory_total_gib, 1)} GiB`;
  setResourceState(
    "memory-state",
    memoryTone === "safe" ? "充足" : memoryTone === "watch" ? "偏高" : "紧张",
    memoryTone,
  );
  setMeter("memory-meter", system.memory_used_percent, memoryTone);

  $("swap-percent").textContent = `${formatNumber(system.swap_percent, 0)}%`;
  $("swap-used").textContent =
    `${formatNumber(system.swap_used_gib, 1)} GiB 已用`;
  $("swap-detail").textContent =
    `共 ${formatNumber(system.swap_total_gib, 1)} GiB`;
  setResourceState(
    "swap-state",
    swapTone === "safe" ? "正常" : swapTone === "watch" ? "偏高" : "高压",
    swapTone,
  );
  setMeter("swap-meter", system.swap_percent, swapTone);

  $("resource-candidates").textContent = String(guard.candidate_count || 0);
  setResourceState(
    "resource-guard-state",
    guardHealthy ? "已启用" : "需检查",
    guardTone,
  );
  $("resource-guard-copy").textContent = guard.last_action
    ? `最近动作 ${formatTime(guard.last_action.time)}`
    : "仅治理临时测试进程";
  setMeter(
    "resource-guard-meter",
    Math.min(100, (guard.candidate_count || 0) * 18 + (guardHealthy ? 8 : 100)),
    guardTone,
  );
}

function processMetric(item) {
  return processMode === "cpu"
    ? `${formatNumber(item.cpu_percent, 1)}%`
    : `${formatNumber(item.rss_gib, 2)} GiB`;
}

function processValueTone(item) {
  const value = processMode === "cpu" ? item.cpu_percent : item.rss_gib;
  const watch = processMode === "cpu" ? 80 : 2;
  const danger = processMode === "cpu" ? 200 : 4;
  return value >= danger ? "critical" : value >= watch ? "high" : "";
}

function updateProcessRankings(payload) {
  const resources = payload.resources;
  if (!resources) return;
  const list = $("process-list");
  list.replaceChildren();
  const items = resources.processes?.[processMode] || [];
  $("process-metric-label").textContent = processMode === "cpu" ? "CPU" : "内存";
  $("cpu-tab").classList.toggle("active", processMode === "cpu");
  $("memory-tab").classList.toggle("active", processMode === "memory");

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state horizontal";
    const icon = document.createElement("span");
    icon.className = "empty-icon";
    const copy = document.createElement("p");
    copy.textContent = "当前没有可展示的进程数据";
    empty.append(icon, copy);
    list.append(empty);
    return;
  }

  items.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "process-row";
    const name = document.createElement("div");
    name.className = "process-name";
    const rank = document.createElement("span");
    rank.className = "process-rank";
    rank.textContent = String(index + 1).padStart(2, "0");
    const text = document.createElement("div");
    text.className = "process-name-text";
    const strong = document.createElement("strong");
    strong.textContent = item.name || "未知进程";
    const meta = document.createElement("span");
    meta.textContent = `PID ${item.pid}${item.owned ? " · 当前用户" : ""}`;
    text.append(strong, meta);
    name.append(rank, text);
    const elapsed = document.createElement("span");
    elapsed.className = "process-elapsed";
    elapsed.textContent = item.elapsed;
    const value = document.createElement("span");
    value.className = `process-value ${processValueTone(item)}`;
    value.textContent = processMetric(item);
    row.append(name, elapsed, value);
    list.append(row);
  });
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds))) return "--";
  const hours = Math.round(Number(seconds) / 3600);
  return hours >= 1 ? `${hours} 小时` : `${Math.round(Number(seconds) / 60)} 分钟`;
}

function updateResourcePolicy(payload) {
  const guard = payload.resources?.guard;
  if (!guard) return;
  const healthy = guard.loaded && guard.enabled && guard.last_exit_code === 0;
  const tone = guard.last_action ? "watch" : healthy ? "safe" : "danger";
  setPill(
    $("resource-policy-state"),
    guard.last_action ? "有治理记录" : healthy ? "保守模式" : "需检查",
    tone,
  );
  $("resource-policy-title").textContent = healthy
    ? "只治理临时失控测试"
    : "资源守护未正常加载";
  $("resource-policy-description").textContent = healthy
    ? "系统进程、浏览器、Codex 和业务服务只进入排行；仅临时 Mach-O 测试进程在持续异常且满足时间门槛时才自动处理。"
    : "请检查资源守护 LaunchAgent 和错误日志。";
  $("resource-cpu-threshold").textContent =
    `≥ ${formatNumber(guard.cpu_threshold_percent, 0)}% × ${guard.cpu_streak_required || "--"} 次`;
  $("resource-memory-threshold").textContent =
    `≥ ${formatNumber(guard.memory_threshold_gib, 0)} GiB × ${guard.memory_streak_required || "--"} 次`;
  $("resource-min-runtime").textContent = formatDuration(guard.min_runtime_seconds);
  $("resource-max-runtime").textContent = formatDuration(guard.max_runtime_seconds);

  const receipt = $("resource-action-receipt");
  receipt.classList.toggle("danger", Boolean(guard.last_action));
  const copy = receipt.querySelector("p");
  if (guard.last_action) {
    const action = guard.last_action;
    copy.textContent =
      `${formatTime(action.time)} · ${action.signal} · PID ${action.pid} · ` +
      `${(action.reasons || []).join(", ")}`;
  } else {
    copy.textContent = `暂无自动治理动作 · ${guard.candidate_count || 0} 个观察候选`;
  }
}

function pushHistory(payload) {
  const now = new Date(payload.timestamp).getTime();
  const previous = history.at(-1);
  if (!previous || now - previous.time >= REFRESH_MS - 500) {
    history.push({ time: now, value: payload.disk.free_gib });
  } else {
    previous.value = payload.disk.free_gib;
    previous.time = now;
  }
  if (history.length > HISTORY_LIMIT) {
    history.splice(0, history.length - HISTORY_LIMIT);
  }
}

function svgElement(name, attributes = {}) {
  const node = document.createElementNS(NS, name);
  Object.entries(attributes).forEach(([key, value]) =>
    node.setAttribute(key, String(value)),
  );
  return node;
}

function drawTrend(payload) {
  pushHistory(payload);
  const width = 780;
  const height = 230;
  const padding = { top: 15, right: 8, bottom: 13, left: 38 };
  const values = history.map((item) => item.value);
  const threshold = payload.guard.threshold_gib;
  const target = payload.guard.target_gib;
  const minValue = Math.max(0, Math.min(...values, threshold) - 3);
  const maxValue = Math.max(...values, target) + 3;
  const span = Math.max(1, maxValue - minValue);
  const x = (index) =>
    padding.left +
    (history.length === 1
      ? (width - padding.left - padding.right) / 2
      : (index / (history.length - 1)) *
        (width - padding.left - padding.right));
  const y = (value) =>
    padding.top +
    ((maxValue - value) / span) *
      (height - padding.top - padding.bottom);

  const grid = $("chart-grid");
  grid.replaceChildren();
  [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
    const gridY =
      padding.top + ratio * (height - padding.top - padding.bottom);
    grid.append(
      svgElement("line", {
        x1: padding.left,
        y1: gridY,
        x2: width - padding.right,
        y2: gridY,
        class: "chart-grid-line",
      }),
    );
    const labelValue = maxValue - ratio * span;
    const label = svgElement("text", {
      x: 0,
      y: gridY + 4,
      class: "chart-grid-label",
    });
    label.textContent = `${formatNumber(labelValue, 0)}G`;
    grid.append(label);
  });
  if (threshold >= minValue && threshold <= maxValue) {
    grid.append(
      svgElement("line", {
        x1: padding.left,
        y1: y(threshold),
        x2: width - padding.right,
        y2: y(threshold),
        class: "chart-threshold",
      }),
    );
  }

  const points = history.map((item, index) => [x(index), y(item.value)]);
  const path = points
    .map(([px, py], index) => `${index === 0 ? "M" : "L"} ${px} ${py}`)
    .join(" ");
  const baseline = height - padding.bottom;
  const area =
    points.length > 0
      ? `${path} L ${points.at(-1)[0]} ${baseline} L ${points[0][0]} ${baseline} Z`
      : "";
  $("chart-line").setAttribute("d", path);
  $("chart-area").setAttribute("d", area);
  const pointGroup = $("chart-points");
  pointGroup.replaceChildren();
  if (points.length) {
    const [px, py] = points.at(-1);
    pointGroup.append(
      svgElement("circle", {
        cx: px,
        cy: py,
        r: 5,
        class: "chart-point",
      }),
    );
  }

  const delta = values.at(-1) - values[0];
  $("trend-delta").textContent =
    history.length < 2
      ? "建立基线"
      : `${delta >= 0 ? "+" : ""}${formatNumber(delta, 2)} GiB`;
  $("trend-start").textContent =
    history.length > 1 ? formatTime(history[0].time).slice(-8) : "现在";
  $("trend-end").textContent = formatTime(history.at(-1).time).slice(-8);
}

function updateStorage(payload) {
  const storage = payload.storage;
  $("sample-time").textContent = storage.sampled_at
    ? `采样 ${formatTime(storage.sampled_at).slice(-8)}`
    : "正在采样";
  $("go-cache-size").textContent = formatSize(storage.go_cache_gib);
  $("module-cache-size").textContent =
    storage.module_cache_gib === null ||
    storage.module_cache_gib === undefined
      ? "受保护"
      : formatSize(storage.module_cache_gib);
  $("go-temp-size").textContent = formatSize(storage.go_temp_gib);
  $("test-binary-size").textContent = formatSize(storage.test_binary_gib);
  $("go-temp-count").textContent = `${storage.go_temp_count || 0} 个目录`;
  $("test-binary-count").textContent =
    `${storage.test_binary_count || 0} 个文件`;

  const values = [
    storage.go_cache_gib || 0,
    storage.module_cache_gib || 0,
    storage.go_temp_gib || 0,
    storage.test_binary_gib || 0,
  ];
  const max = Math.max(...values, 1);
  [
    ["go-cache-bar", values[0]],
    ["module-cache-bar", values[1]],
    ["go-temp-bar", values[2]],
    ["test-binary-bar", values[3]],
  ].forEach(([id, value]) => {
    $(id).style.setProperty("--bar-width", `${Math.max(4, (value / max) * 100)}%`);
  });
}

function actionLabel(action) {
  const labels = {
    test_binary: "测试二进制",
    isolated_go_cache: "独立 Go 缓存",
    go_temp: "Go 临时目录",
    shared_go_cache: "共享构建缓存",
    skip: "已跳过",
    error: "错误",
  };
  return labels[action.kind] || action.kind || "操作";
}

function updateReceipt(payload) {
  const event = payload.guard.last_event;
  const content = $("receipt-content");
  content.replaceChildren();
  if (!event) {
    $("receipt-time").textContent = "暂无记录";
    const empty = document.createElement("div");
    empty.className = "empty-state horizontal";
    const icon = document.createElement("span");
    icon.className = "empty-icon";
    const copy = document.createElement("p");
    copy.textContent = "低空间触发后，这里会显示清理结果与跳过原因。";
    empty.append(icon, copy);
    content.append(empty);
    return;
  }

  $("receipt-time").textContent = formatTime(event.time);
  const stats = document.createElement("div");
  stats.className = "receipt-stats";
  [
    ["清理前", `${formatNumber(event.before_free_gib, 1)} GiB`],
    ["释放空间", `${formatNumber(event.reclaimed_gib, 2)} GiB`],
    ["清理后", `${formatNumber(event.after_free_gib, 1)} GiB`],
  ].forEach(([label, value]) => {
    const stat = document.createElement("div");
    stat.className = "receipt-stat";
    const span = document.createElement("span");
    span.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    stat.append(span, strong);
    stats.append(stat);
  });
  content.append(stats);

  const actions = document.createElement("div");
  actions.className = "receipt-actions";
  (event.actions || []).slice(0, 14).forEach((action) => {
    const tag = document.createElement("span");
    tag.className = `receipt-action ${action.kind === "skip" ? "skip" : ""} ${
      action.kind === "error" ? "error" : ""
    }`;
    const name = action.path ? action.path.split("/").at(-1) : "";
    tag.textContent =
      `${actionLabel(action)}${name ? ` · ${name}` : ""}` +
      `${action.reason ? ` · ${action.reason}` : ""}`;
    tag.title = action.path || action.reason || "";
    actions.append(tag);
  });
  if (!(event.actions || []).length) {
    const tag = document.createElement("span");
    tag.className = "receipt-action";
    tag.textContent = "没有符合条件的可清理目标";
    actions.append(tag);
  }
  content.append(actions);
}

function updateConnection(online, timestamp) {
  const dot = $("live-dot");
  dot.className = `live-dot ${online ? "online" : "offline"}`;
  $("connection-label").textContent = online ? "实时连接" : "连接中断";
  $("last-updated").textContent = online
    ? formatTime(timestamp).slice(-8)
    : "重试中";
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3800);
}

function cleanupReasonLabel(reason) {
  const labels = {
    active_build: "存在活跃 Go 构建",
    active_or_not_quiet: "缓存正在使用或未静默满 5 分钟",
    process_check_failed: "进程检查失败",
    open_file_check_failed: "打开文件检查失败",
    open_or_check_failed: "文件正在使用或检查失败",
    changed_since_scan: "扫描后内容发生变化",
    size_changed_since_scan: "扫描后大小发生变化",
    process_reference: "仍被进程引用",
    build_or_open_file_started: "执行时构建或文件占用启动",
    cleanup_plan_expired: "清理计划已过期，请重新扫描",
    cleanup_plan_not_found: "清理计划不存在，请重新扫描",
    cleanup_busy: "自动清理正在运行，请稍后重试",
    invalid_candidate_selection: "候选选择无效",
  };
  return labels[reason] || reason || "已安全跳过";
}

function categoryLabel(category) {
  const labels = {
    test_binary: "大型测试二进制",
    isolated_go_cache: "独立 Go 缓存",
    go_temp: "Go 临时目录",
    shared_go_cache: "共享 Go 构建缓存",
  };
  return labels[category] || category;
}

function selectedCandidates() {
  if (!cleanupPlan) return [];
  return cleanupPlan.candidates.filter((candidate) =>
    cleanupSelected.has(candidate.id),
  );
}

function selectedBytes() {
  return selectedCandidates().reduce(
    (total, candidate) => total + candidate.bytes,
    0,
  );
}

function updateCleanupSelection() {
  const selected = selectedCandidates();
  const count = selected.length;
  const bytes = selectedBytes();
  $("cleanup-selected-summary").textContent =
    `已选 ${count} 项 · ${formatBytes(bytes)}`;
  $("cleanup-execute-button").disabled = count === 0 || cleanupBusy;
  const checkboxes = [
    ...document.querySelectorAll(".cleanup-item input[type='checkbox']"),
  ];
  const allSelected =
    checkboxes.length > 0 &&
    checkboxes.every((checkbox) => checkbox.checked);
  $("cleanup-select-all").checked = allSelected;
  $("cleanup-select-all").indeterminate =
    !allSelected && checkboxes.some((checkbox) => checkbox.checked);
}

function renderCleanupReceipt(receipt) {
  const container = $("manual-cleanup-receipt");
  container.replaceChildren();
  if (!receipt) {
    container.hidden = true;
    return;
  }
  const values = [
    ["清理前", `${formatNumber(receipt.before_free_gib, 1)} GiB`],
    ["实际释放", `${formatNumber(receipt.reclaimed_gib, 2)} GiB`],
    ["已删除", `${receipt.deleted_count || 0} 项`],
    [
      "跳过 / 错误",
      `${receipt.skipped_count || 0} / ${receipt.error_count || 0}`,
    ],
  ];
  values.forEach(([label, value]) => {
    const card = document.createElement("div");
    const span = document.createElement("span");
    span.textContent = label;
    const strong = document.createElement("strong");
    strong.textContent = value;
    card.append(span, strong);
    container.append(card);
  });
  container.hidden = false;
}

function renderCleanupPlan(plan) {
  cleanupPlan = plan;
  cleanupSelected = new Set(
    plan.candidates
      .filter(
        (candidate) => candidate.category !== "shared_go_cache",
      )
      .map((candidate) => candidate.id),
  );
  $("cleanup-summary").hidden = false;
  $("cleanup-items-wrap").hidden = false;
  $("cleanup-total-gib").textContent = formatSize(plan.total_gib);
  $("cleanup-expiry").textContent =
    `计划有效至 ${formatTime(plan.expires_at).slice(-8)}`;
  setPill(
    $("cleanup-state"),
    plan.candidate_count ? "扫描完成" : "无安全候选",
    plan.candidate_count ? "watch" : "safe",
  );

  const categories = $("cleanup-categories");
  categories.replaceChildren();
  plan.categories.forEach((category) => {
    const card = document.createElement("div");
    card.className = "cleanup-category";
    const span = document.createElement("span");
    span.textContent = `${category.label} · ${category.count} 项`;
    const strong = document.createElement("strong");
    strong.textContent = formatBytes(category.bytes);
    card.append(span, strong);
    categories.append(card);
  });
  if (!plan.categories.length) {
    const card = document.createElement("div");
    card.className = "cleanup-category";
    const span = document.createElement("span");
    span.textContent = "扫描结果";
    const strong = document.createElement("strong");
    strong.textContent = "没有符合条件的项目";
    card.append(span, strong);
    categories.append(card);
  }

  const items = $("cleanup-items");
  items.replaceChildren();
  plan.candidates.forEach((candidate) => {
    const row = document.createElement("label");
    row.className = "cleanup-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.candidateId = candidate.id;
    checkbox.checked = cleanupSelected.has(candidate.id);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) cleanupSelected.add(candidate.id);
      else cleanupSelected.delete(candidate.id);
      updateCleanupSelection();
    });
    const main = document.createElement("div");
    main.className = "cleanup-item-main";
    const strong = document.createElement("strong");
    strong.textContent = categoryLabel(candidate.category);
    const code = document.createElement("code");
    code.textContent = candidate.path;
    main.append(strong, code);
    const size = document.createElement("span");
    size.className = "cleanup-item-size";
    size.textContent = formatBytes(candidate.bytes);
    row.append(checkbox, main, size);
    items.append(row);
  });

  const skipped = $("cleanup-skipped");
  skipped.replaceChildren();
  plan.skipped.forEach((item) => {
    const tag = document.createElement("span");
    tag.className = "cleanup-skip";
    tag.textContent =
      `${item.group || "项目"} · ${cleanupReasonLabel(item.reason)}` +
      `${item.count ? ` · ${item.count} 个进程` : ""}`;
    skipped.append(tag);
  });
  updateCleanupSelection();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(120000),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.code = payload.error;
    throw error;
  }
  return payload;
}

async function scanCleanup() {
  if (cleanupBusy) return;
  cleanupBusy = true;
  $("cleanup-scan-button").disabled = true;
  setPill($("cleanup-state"), "扫描中", "watch");
  try {
    const payload = await postJson("/api/cleanup/scan", {});
    renderCleanupPlan(payload.plan);
    renderCleanupReceipt(null);
    showToast(
      payload.plan.candidate_count
        ? `扫描完成：${payload.plan.candidate_count} 项，预计 ${formatSize(payload.plan.total_gib)}`
        : "扫描完成，没有符合安全条件的可清理项目。",
    );
  } catch (error) {
    setPill($("cleanup-state"), "扫描失败", "danger");
    showToast(`扫描失败：${cleanupReasonLabel(error.code || error.message)}`);
  } finally {
    cleanupBusy = false;
    $("cleanup-scan-button").disabled = false;
    updateCleanupSelection();
  }
}

function openCleanupConfirmation() {
  const selected = selectedCandidates();
  if (!selected.length) return;
  $("confirm-count").textContent = String(selected.length);
  $("confirm-size").textContent = formatBytes(selectedBytes());
  const list = $("confirm-list");
  list.replaceChildren();
  const grouped = new Map();
  selected.forEach((candidate) => {
    const current = grouped.get(candidate.category) || {
      count: 0,
      bytes: 0,
    };
    current.count += 1;
    current.bytes += candidate.bytes;
    grouped.set(candidate.category, current);
  });
  grouped.forEach((value, category) => {
    const tag = document.createElement("span");
    tag.textContent =
      `${categoryLabel(category)} · ${value.count} 项 · ${formatBytes(value.bytes)}`;
    list.append(tag);
  });
  $("cleanup-confirm-modal").hidden = false;
  document.body.classList.add("modal-open");
  $("cleanup-cancel-button").focus();
}

function closeCleanupConfirmation() {
  $("cleanup-confirm-modal").hidden = true;
  document.body.classList.remove("modal-open");
  $("cleanup-execute-button").focus();
}

async function executeCleanup() {
  const selected = selectedCandidates();
  if (!cleanupPlan || !selected.length || cleanupBusy) return;
  cleanupBusy = true;
  $("cleanup-confirm-button").disabled = true;
  $("cleanup-cancel-button").disabled = true;
  $("cleanup-confirm-button").textContent = "清理中";
  setPill($("cleanup-state"), "执行中", "danger");
  try {
    const payload = await postJson("/api/cleanup/execute", {
      token: cleanupPlan.token,
      candidate_ids: selected.map((candidate) => candidate.id),
    });
    closeCleanupConfirmation();
    renderCleanupReceipt(payload.receipt);
    cleanupPlan = null;
    cleanupSelected.clear();
    $("cleanup-summary").hidden = true;
    $("cleanup-items-wrap").hidden = true;
    setPill(
      $("cleanup-state"),
      payload.receipt.error_count ? "部分完成" : "清理完成",
      payload.receipt.error_count ? "watch" : "safe",
    );
    showToast(
      `主动清理完成：释放 ${formatNumber(payload.receipt.reclaimed_gib, 2)} GiB，` +
        `删除 ${payload.receipt.deleted_count} 项，跳过 ${payload.receipt.skipped_count} 项。`,
    );
    await refresh();
  } catch (error) {
    closeCleanupConfirmation();
    setPill($("cleanup-state"), "需要重新扫描", "watch");
    showToast(`清理未执行：${cleanupReasonLabel(error.code || error.message)}`);
    cleanupPlan = null;
    cleanupSelected.clear();
    $("cleanup-execute-button").disabled = true;
  } finally {
    cleanupBusy = false;
    $("cleanup-confirm-button").disabled = false;
    $("cleanup-cancel-button").disabled = false;
    $("cleanup-confirm-button").textContent = "确认清理";
  }
}

function render(payload) {
  lastPayload = payload;
  updateSystemResources(payload);
  updateGauge(payload);
  updateGuard(payload);
  updateBuilds(payload);
  drawTrend(payload);
  updateStorage(payload);
  updateProcessRankings(payload);
  updateResourcePolicy(payload);
  updateReceipt(payload);
  updateConnection(true, payload.timestamp);
}

async function refresh() {
  try {
    const response = await fetch("/api/status", {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    render(payload);
  } catch (error) {
    updateConnection(false);
    if (!lastPayload) {
      setPill($("disk-state"), "数据不可用", "danger");
      setPill($("guard-state"), "连接失败", "danger");
    }
    showToast(`无法读取本机监控数据，正在自动重试。`);
  }
}

refresh();
setInterval(refresh, REFRESH_MS);

$("cpu-tab").addEventListener("click", () => {
  processMode = "cpu";
  if (lastPayload) updateProcessRankings(lastPayload);
});

$("memory-tab").addEventListener("click", () => {
  processMode = "memory";
  if (lastPayload) updateProcessRankings(lastPayload);
});

$("cleanup-scan-button").addEventListener("click", scanCleanup);

$("cleanup-select-all").addEventListener("change", (event) => {
  if (!cleanupPlan) return;
  document
    .querySelectorAll(".cleanup-item input[type='checkbox']")
    .forEach((checkbox) => {
      checkbox.checked = event.target.checked;
      const candidateId = checkbox.dataset.candidateId;
      if (checkbox.checked) cleanupSelected.add(candidateId);
      else cleanupSelected.delete(candidateId);
    });
  updateCleanupSelection();
});

$("cleanup-execute-button").addEventListener(
  "click",
  openCleanupConfirmation,
);
$("cleanup-cancel-button").addEventListener(
  "click",
  closeCleanupConfirmation,
);
$("cleanup-confirm-button").addEventListener("click", executeCleanup);
$("cleanup-confirm-modal").addEventListener("click", (event) => {
  if (event.target === $("cleanup-confirm-modal") && !cleanupBusy) {
    closeCleanupConfirmation();
  }
});
document.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" &&
    !$("cleanup-confirm-modal").hidden &&
    !cleanupBusy
  ) {
    closeCleanupConfirmation();
  }
});
