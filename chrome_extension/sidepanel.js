const API_URL = "http://localhost:8000/chat";

const modelSelect = document.getElementById("model-select");
const apiSetup = document.getElementById("api-setup");
const chatView = document.getElementById("chat-view");
const apiKeyInput = document.getElementById("api-key-input");
const apiSaveBtn = document.getElementById("api-save-btn");
const changeKeyBtn = document.getElementById("change-key-btn");
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send");
const messagesEl = document.getElementById("messages");
const emptyState = document.getElementById("empty-state");
const emptyLogo = document.getElementById("empty-logo");
const fileInput = document.getElementById("file-input");
const filePreview = document.getElementById("file-preview");

let attachedFile = null;

const hasChromeStorage =
  typeof chrome !== "undefined" && chrome.storage && chrome.storage.local;

function storageGet(key) {
  return new Promise((resolve) => {
    if (hasChromeStorage) {
      try {
        chrome.storage.local.get([key], (result) => {
          if (chrome.runtime && chrome.runtime.lastError) {
            resolve(localStorage.getItem(key));
            return;
          }
          const val =
            result && Object.prototype.hasOwnProperty.call(result, key)
              ? result[key]
              : null;
          resolve(val == null ? null : val);
        });
      } catch (e) {
        resolve(localStorage.getItem(key));
      }
    } else {
      resolve(localStorage.getItem(key));
    }
  });
}

function storageSet(key, val) {
  return new Promise((resolve) => {
    if (hasChromeStorage) {
      try {
        chrome.storage.local.set({ [key]: val }, () => {
          if (chrome.runtime && chrome.runtime.lastError) {
            try { localStorage.setItem(key, val); } catch (_) {}
          }
          resolve();
        });
      } catch (e) {
        try { localStorage.setItem(key, val); } catch (_) {}
        resolve();
      }
    } else {
      try { localStorage.setItem(key, val); } catch (_) {}
      resolve();
    }
  });
}

function getProvider() { return modelSelect.value.split("|")[0]; }
function getModelId() { return modelSelect.value.split("|")[1]; }

function showChat() {
  apiSetup.style.display = "none";
  chatView.classList.add("active");
  changeKeyBtn.style.display = "block";
  setTimeout(() => { if (messageInput) messageInput.focus(); }, 50);
}

function showSetup() {
  chatView.classList.remove("active");
  apiSetup.style.display = "flex";
  changeKeyBtn.style.display = "none";
  apiKeyInput.value = "";
  setTimeout(() => apiKeyInput.focus(), 100);
}

function refreshViewForProvider() {
  storageGet(`apiKey_${getProvider()}`).then((val) => {
    if (val) showChat(); else showSetup();
  });
}

storageGet("modelValue").then((val) => {
  if (val) modelSelect.value = val;
  refreshViewForProvider();
});

modelSelect.addEventListener("change", () => {
  storageSet("modelValue", modelSelect.value);
  refreshViewForProvider();
});

apiSaveBtn.addEventListener("click", () => {
  const key = apiKeyInput.value.trim();
  if (!key) { apiKeyInput.style.borderColor = "#da1e28"; return; }
  apiSaveBtn.disabled = true;
  storageSet(`apiKey_${getProvider()}`, key).then(() => {
    apiSaveBtn.disabled = false;
    showChat();
  });
});

apiKeyInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); apiSaveBtn.click(); }
});

apiKeyInput.addEventListener("input", () => {
  apiKeyInput.style.borderColor = "";
});

changeKeyBtn.addEventListener("click", () => showSetup());

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) { attachedFile = file; filePreview.textContent = `Attached: ${file.name}`; }
});

function hideEmptyState() {
  if (emptyState) emptyState.style.display = "none";
}

function appendMessage(text, role) {
  hideEmptyState();
  const wrapper = document.createElement("div");
  wrapper.className = `message message-${role === "error" ? "bot" : role}`;
  if (role === "error") wrapper.classList.add("error");
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendThinking() {
  hideEmptyState();
  if (emptyLogo) emptyLogo.classList.add("bob-thinking");
  const wrapper = document.createElement("div");
  wrapper.className = "message message-bot";
  wrapper.id = "thinking-msg";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const dots = document.createElement("div");
  dots.className = "thinking-dots";
  dots.innerHTML = "<span></span><span></span><span></span>";
  bubble.appendChild(dots);
  wrapper.appendChild(bubble);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeThinking() {
  const el = document.getElementById("thinking-msg");
  if (el) el.remove();
  if (emptyLogo) emptyLogo.classList.remove("bob-thinking");
}

async function sendMessage() {
  const message = messageInput.value.trim();
  if (!message && !attachedFile) return;
  const provider = getProvider();
  const model = getModelId();

  const apiKey = await storageGet(`apiKey_${provider}`);
  if (!apiKey) { showSetup(); return; }

  appendMessage(message + (attachedFile ? ` [${attachedFile.name}]` : ""), "user");
  messageInput.value = "";
  attachedFile = null;
  fileInput.value = "";
  filePreview.textContent = "";
  sendButton.disabled = true;
  appendThinking();

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, api_key: apiKey, model, provider }),
    });
    removeThinking();
    if (!res.ok) {
      appendMessage(`Error ${res.status}: ${await res.text()}`, "error");
      return;
    }
    const data = await res.json();
    appendMessage(data.response || "(empty response)", "bot");
  } catch (err) {
    removeThinking();
    appendMessage("Request failed. Make sure api_bridge.py is running on localhost:8000", "error");
  } finally {
    sendButton.disabled = false;
    messageInput.focus();
  }
}

sendButton.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
