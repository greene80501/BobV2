"use strict";

const BOB_WS_URL     = "ws://localhost:9876";
const RECONNECT_MS   = 1500;
const NAV_SETTLE_MS  = 1800;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const statusPill   = document.getElementById("status-pill");
const statusText   = document.getElementById("status-text");
const topbarSub    = document.getElementById("topbar-sub");
const messagesEl   = document.getElementById("messages");
const emptyState   = document.getElementById("empty-state");
const emptyLogo    = document.getElementById("empty-logo");
const emptySubtitle = document.getElementById("empty-subtitle");
const actionRow    = document.getElementById("action-row");
const actionText   = document.getElementById("action-text");
const actionCount  = document.getElementById("action-count");
const thinkingDots = document.getElementById("thinking-dots");

let ws = null;
let reconnectTimer = null;
let count = 0;

// ── Status helpers ────────────────────────────────────────────────────────────

function setStatus(state) {
  statusPill.className = `status-pill ${state}`;
  if (state === "connected") {
    statusText.textContent = "Connected";
    topbarSub.textContent  = "bob is ready to browse";
    emptySubtitle.textContent = "Ask bob to navigate to a page, click something, or take a screenshot.";
  } else if (state === "connecting") {
    statusText.textContent = "Connecting";
    topbarSub.textContent  = "Looking for bob on ws://localhost:9876…";
    emptySubtitle.innerHTML = "Start bob in your terminal,<br>then ask it to browse the web.";
  } else {
    statusText.textContent = "Disconnected";
    topbarSub.textContent  = "Start bob in your terminal to connect";
    emptySubtitle.innerHTML = "Start bob in your terminal,<br>then ask it to browse the web.";
  }
}

// ── Activity log ──────────────────────────────────────────────────────────────

function hideEmptyState() {
  if (emptyState) emptyState.style.display = "none";
}

function ts() {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

function appendEntry(label, body, kind = "info") {
  hideEmptyState();
  count++;
  actionCount.textContent = `${count} action${count === 1 ? "" : "s"}`;

  const wrapper = document.createElement("div");
  wrapper.className = `message message-bot ${kind}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const meta = document.createElement("div");
  meta.className = "bubble-meta";
  meta.textContent = `${ts()}  ${label}`;

  bubble.appendChild(meta);

  if (body) {
    const bodyEl = document.createElement("div");
    bodyEl.textContent = body;
    bubble.appendChild(bodyEl);
  }

  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Action bar ────────────────────────────────────────────────────────────────

function showAction(text) {
  actionRow.classList.add("active");
  thinkingDots.style.display = "flex";
  actionText.textContent = text;
  if (emptyLogo) emptyLogo.classList.add("bob-thinking");
}

function clearAction() {
  actionRow.classList.remove("active");
  thinkingDots.style.display = "none";
  actionText.textContent = "Waiting for bob…";
  if (emptyLogo) emptyLogo.classList.remove("bob-thinking");
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  clearTimeout(reconnectTimer);
  setStatus("connecting");

  try {
    ws = new WebSocket(BOB_WS_URL);
  } catch {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    setStatus("connected");
    appendEntry("Connected", "bob session is active", "ok");
  };

  ws.onclose = () => {
    ws = null;
    clearAction();
    setStatus("disconnected");
    appendEntry("Disconnected", "Reconnecting in 3s…", "error");
    scheduleReconnect();
  };

  ws.onerror = () => { /* onclose fires immediately after */ };

  ws.onmessage = async (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    if (msg.type === "connected") {
      appendEntry("Session ready", "", "info");
      return;
    }

    const { id, action, params } = msg;
    if (!id || !action) return;

    const label = actionLabel(action, params || {});
    showAction(label);
    appendEntry(label, paramSummary(action, params || {}), "info");

    let result, error;
    try {
      result = await dispatch(action, params || {});
    } catch (err) {
      error = err.message || String(err);
    }

    clearAction();

    if (error) {
      appendEntry(label + " — failed", error, "error");
      safeSend({ id, error });
    } else {
      const preview = previewResult(action, result);
      appendEntry(label + " — done", preview, "ok");
      safeSend({ id, result: result ?? "" });
    }
  };
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, RECONNECT_MS);
}

function safeSend(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

function actionLabel(action, params) {
  switch (action) {
    case "navigate":        return `Navigate → ${(params.url || "").replace(/^https?:\/\//, "")}`;
    case "get_page_text":   return "Read page text";
    case "get_page_html":   return "Read page HTML";
    case "screenshot":      return "Take screenshot";
    case "click":           return `Click "${params.selector || ""}"`;
    case "form_input":      return `Fill in "${params.selector || ""}"`;
    case "execute_js":      return `Run JS`;
    case "find_elements":   return `Find "${params.selector || ""}"`;
    case "scroll":          return `Scroll (${params.x || 0}, ${params.y || 0})`;
    case "get_current_url": return "Get current URL";
    case "ping":            return "Ping";
    default:                return action;
  }
}

function paramSummary(action, params) {
  if (action === "navigate")    return params.url || "";
  if (action === "execute_js")  return (params.code || "").slice(0, 120);
  if (action === "form_input")  return `${params.selector} = "${params.value}"`;
  return "";
}

function previewResult(action, result) {
  if (!result || typeof result !== "string") return "";
  if (action === "screenshot") return "(image captured)";
  if (action === "navigate")   return result;
  return result.slice(0, 200).replace(/\n/g, " ");
}

// ── Command dispatch ──────────────────────────────────────────────────────────

async function dispatch(action, params) {
  switch (action) {
    case "navigate":        return await cmdNavigate(params);
    case "get_page_text":   return await cmdGetPageText();
    case "get_page_html":   return await cmdGetPageHtml();
    case "screenshot":      return await cmdScreenshot();
    case "click":           return await cmdClick(params);
    case "form_input":      return await cmdFormInput(params);
    case "execute_js":      return await cmdExecuteJs(params);
    case "find_elements":   return await cmdFindElements(params);
    case "scroll":          return await cmdScroll(params);
    case "get_current_url": return await cmdGetCurrentUrl();
    case "ping":            return "pong";
    default: throw new Error(`Unknown action: ${action}`);
  }
}

// ── Active tab helper ─────────────────────────────────────────────────────────

async function activeTab({ allowInternal = false } = {}) {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs.length) throw new Error("No active tab found");
  const tab = tabs[0];
  if (!allowInternal && tab.url && (tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://") || tab.url.startsWith("about:"))) {
    throw new Error(`Cannot access Chrome internal page (${tab.url}). Navigate to a regular website first.`);
  }
  return tab;
}

// ── Commands ──────────────────────────────────────────────────────────────────

async function cmdNavigate({ url }) {
  if (!url) throw new Error("url is required");
  const tab = await activeTab({ allowInternal: true });
  await chrome.tabs.update(tab.id, { url });
  await waitForTabLoad(tab.id);
  return `Navigated to ${url}`;
}

function waitForTabLoad(tabId) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (!done) {
        done = true;
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    };
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") finish();
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(finish, NAV_SETTLE_MS);
  });
}

async function cmdGetPageText() {
  const tab = await activeTab();
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => document.body ? document.body.innerText : "",
  });
  const text = results[0]?.result || "";
  return text.length > 80000 ? text.slice(0, 80000) + "\n[truncated]" : text;
}

async function cmdGetPageHtml() {
  const tab = await activeTab();
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => document.documentElement.outerHTML,
  });
  const html = results[0]?.result || "";
  return html.length > 100000 ? html.slice(0, 100000) + "\n[truncated]" : html;
}

async function cmdScreenshot() {
  const tab = await activeTab({ allowInternal: true });
  if (!tab.url || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://") || tab.url.startsWith("about:")) {
    throw new Error(`Cannot screenshot ${tab.url || "this page"} — navigate to a regular website first.`);
  }
  return await chrome.tabs.captureVisibleTab(null, { format: "png" });
}

async function cmdClick({ selector }) {
  if (!selector) throw new Error("selector is required");
  const tab = await activeTab();
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.focus();
      el.click();
      return true;
    },
    args: [selector],
  });
  if (!results[0]?.result) throw new Error(`Element not found: ${selector}`);
  return `Clicked ${selector}`;
}

async function cmdFormInput({ selector, value }) {
  if (!selector) throw new Error("selector is required");
  const tab = await activeTab();
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel, val) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.focus();
      if (el.tagName === "SELECT") {
        el.value = val;
      } else {
        const nativeSetter = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value")?.set;
        if (nativeSetter) nativeSetter.call(el, val);
        else el.value = val;
      }
      el.dispatchEvent(new Event("input",  { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    },
    args: [selector, value ?? ""],
  });
  if (!results[0]?.result) throw new Error(`Element not found: ${selector}`);
  return `Set "${selector}"`;
}

async function cmdExecuteJs({ code }) {
  if (!code) throw new Error("code is required");
  const tab = await activeTab();
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (c) => {
      try {
        const result = (0, eval)(c); // eslint-disable-line no-eval
        return result !== undefined ? String(result) : "(undefined)";
      } catch (e) {
        return `Error: ${e.message}`;
      }
    },
    args: [code],
  });
  return results[0]?.result ?? "";
}

async function cmdFindElements({ selector, limit = 20 }) {
  if (!selector) throw new Error("selector is required");
  const tab = await activeTab();
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (sel, lim) => {
      return Array.from(document.querySelectorAll(sel))
        .slice(0, lim)
        .map((el) => ({
          tag:   el.tagName.toLowerCase(),
          text:  (el.innerText || el.value || el.getAttribute("alt") || "").slice(0, 200),
          href:  el.href   || null,
          id:    el.id     || null,
          cls:   el.className || null,
          type:  el.type   || null,
          value: (el.tagName === "INPUT" || el.tagName === "SELECT") ? el.value : null,
        }));
    },
    args: [selector, limit],
  });
  return JSON.stringify(results[0]?.result ?? [], null, 2);
}

async function cmdScroll({ x = 0, y = 0 }) {
  const tab = await activeTab();
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (dx, dy) => window.scrollBy(dx, dy),
    args: [x, y],
  });
  return `Scrolled by (${x}, ${y})`;
}

async function cmdGetCurrentUrl() {
  const tab = await activeTab({ allowInternal: true });
  return tab.url || "";
}

// ── Boot ──────────────────────────────────────────────────────────────────────
connect();
