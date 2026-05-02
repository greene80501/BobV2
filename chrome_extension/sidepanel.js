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
    case "type_text":       return `Type "${(params.text || "").slice(0, 40)}"`;
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
    case "type_text":       return await cmdTypeText(params);
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
  try {
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
  } catch (err) {
    const msg = err.message || String(err);
    if (msg.includes("Content Security Policy") || msg.includes("unsafe-eval")) {
      return (
        "Error: This page blocks eval() via Content Security Policy. " +
        "Use 'type_text' to type into editors, 'click' to click elements, " +
        "or 'form_input' for standard HTML input fields."
      );
    }
    throw err;
  }
}

async function cmdTypeText({ text, selector }) {
  if (text == null) throw new Error("text is required");
  const tab = await activeTab();

  // Phase 1: <input>/<textarea> — instant value setter (no CDP overhead)
  if (selector) {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (sel) => { const el = document.querySelector(sel); if (el) { el.focus(); el.click(); } },
      args: [selector],
    });
  }
  const nativeResult = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (txt) => {
      const t = document.activeElement;
      if (!t || (t.tagName !== "INPUT" && t.tagName !== "TEXTAREA")) return false;
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(t), "value")?.set;
      if (setter) setter.call(t, (t.value || "") + txt);
      else t.value = (t.value || "") + txt;
      t.dispatchEvent(new Event("input",  { bubbles: true }));
      t.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    },
    args: [text],
  });
  if (nativeResult[0]?.result) return `Typed ${text.length} chars via native-input`;

  // Phase 2: CDP clipboard paste.
  // JavaScript-dispatched events (KeyboardEvent, InputEvent) are isTrusted:false — Google
  // Docs and most canvas editors silently drop them. CDP key events go to the main frame,
  // not the hidden input iframe Google Docs uses. The only reliable path is:
  //   1. Write text to clipboard via CDP Runtime.evaluate (bypasses page CSP)
  //   2. Send Ctrl+V via CDP — Google Docs' paste handler runs in the main frame
  //      and inserts at cursor, no iframe routing required.
  // Side effect: overwrites the user's clipboard.
  const dbg = { tabId: tab.id };
  try {
    await chrome.debugger.attach(dbg, "1.3");
  } catch (err) {
    if ((err.message || "").includes("Another debugger")) {
      try { await chrome.debugger.detach(dbg); } catch (_) {}
      await chrome.debugger.attach(dbg, "1.3");
    } else throw err;
  }

  try {
    // Get click coordinates: use selector's center, or center of viewport
    const coordsExpr = selector
      ? `(function(){const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;const r=el.getBoundingClientRect();return{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()`
      : `({x:Math.round(window.innerWidth/2),y:Math.round(window.innerHeight*0.55)})`;
    const coordsVal = (await chrome.debugger.sendCommand(dbg, "Runtime.evaluate", { expression: `JSON.stringify(${coordsExpr})` })).result?.value;
    const { x, y } = JSON.parse(coordsVal || '{"x":640,"y":400}');

    // Click to ensure the editor has focus (cursor placement)
    await chrome.debugger.sendCommand(dbg, "Input.dispatchMouseEvent", { type: "mousePressed", button: "left", x, y, clickCount: 1 });
    await chrome.debugger.sendCommand(dbg, "Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", x, y, clickCount: 1 });
    await new Promise(r => setTimeout(r, 80));

    // Write to clipboard via CDP Runtime.evaluate (not blocked by CSP — bypasses eval())
    const clipResult = (await chrome.debugger.sendCommand(dbg, "Runtime.evaluate", {
      expression: `(async()=>{try{await navigator.clipboard.writeText(${JSON.stringify(text)});return "ok";}catch(e){return "err:"+e.message;}})()`,
      awaitPromise: true,
      userGesture: true,
    })).result?.value;
    if (typeof clipResult === "string" && clipResult.startsWith("err:")) {
      throw new Error(`Clipboard write failed: ${clipResult.slice(4)}`);
    }

    await new Promise(r => setTimeout(r, 50));

    // Ctrl+V — processed by the app's main-frame paste handler
    await chrome.debugger.sendCommand(dbg, "Input.dispatchKeyEvent", { type: "rawKeyDown", modifiers: 2, key: "v", code: "KeyV", windowsVirtualKeyCode: 86, nativeVirtualKeyCode: 86 });
    await chrome.debugger.sendCommand(dbg, "Input.dispatchKeyEvent", { type: "keyUp",    modifiers: 2, key: "v", code: "KeyV", windowsVirtualKeyCode: 86, nativeVirtualKeyCode: 86 });
    await new Promise(r => setTimeout(r, 120));

    return `Typed ${text.length} chars via clipboard paste (clipboard overwritten)`;
  } finally {
    try { await chrome.debugger.detach(dbg); } catch (_) {}
  }
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
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (dx, dy) => {
      const isScrollable = (el) => {
        if (!el) return false;
        const oy = window.getComputedStyle(el).overflowY;
        return (oy === "auto" || oy === "scroll") && el.scrollHeight > el.clientHeight + 10;
      };

      // 1. Try document.scrollingElement first (works for traditional pages)
      const docEl = document.scrollingElement || document.documentElement;
      const beforeDoc = docEl.scrollTop;
      docEl.scrollBy(dx, dy);
      if (docEl.scrollTop !== beforeDoc) return "document";

      // 2. Try common SPA main containers (LinkedIn, Twitter, etc.)
      const spaCandidates = [
        document.querySelector("main"),
        document.querySelector('[role="main"]'),
        document.querySelector(".scaffold-layout__main"),
        document.querySelector(".scaffold-layout__detail"),
        document.querySelector(".application-outlet"),
        document.querySelector("#main-content"),
        document.querySelector(".feed-container"),
        document.querySelector("[data-view-name]"),
      ];
      for (const el of spaCandidates) {
        if (isScrollable(el)) {
          el.scrollBy(dx, dy);
          return el.tagName + (el.className ? "." + el.className.split(" ")[0] : "");
        }
      }

      // 3. Find the largest scrollable element on the page
      let best = null, bestScrollable = 0;
      document.querySelectorAll("div, main, section, article, aside").forEach((el) => {
        if (isScrollable(el)) {
          const h = el.scrollHeight - el.clientHeight;
          if (h > bestScrollable) { bestScrollable = h; best = el; }
        }
      });
      if (best) {
        best.scrollBy(dx, dy);
        return best.tagName + (best.id ? "#" + best.id : "");
      }

      // 4. Last resort: window
      window.scrollBy(dx, dy);
      return "window";
    },
    args: [x, y],
  });
  const target = results[0]?.result ?? "unknown";
  return `Scrolled by (${x}, ${y}) on ${target}`;
}

async function cmdGetCurrentUrl() {
  const tab = await activeTab({ allowInternal: true });
  return tab.url || "";
}

// ── Boot ──────────────────────────────────────────────────────────────────────
connect();
