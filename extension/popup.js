const statusEl = document.getElementById("status");
const autofillEl = document.getElementById("autofillQueued");

chrome.storage.local.get({ jaAutoFillQueued: true }, data => {
  autofillEl.checked = Boolean(data.jaAutoFillQueued);
});

autofillEl.onchange = () => {
  chrome.storage.local.set({ jaAutoFillQueued: autofillEl.checked });
};

async function check() {
  try {
    const r = await fetch("http://127.0.0.1:8765/health", { method: "GET" });
    if (!r.ok) throw new Error();
    const j = await r.json();
    statusEl.innerHTML = `✅ backend up · queued ${j.counts.queued} · applied ${j.counts.applied}`;
  } catch {
    statusEl.innerHTML = "❌ backend offline — start <code>python -m src.server</code>";
  }
}
check();

document.getElementById("toggle").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await chrome.tabs.sendMessage(tab.id, { type: "JA_TOGGLE" });
  window.close();
};

document.getElementById("dash").onclick = () => {
  chrome.tabs.create({ url: "http://localhost:8501" });
};
