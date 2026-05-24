/* Job Agent content script
 *
 * On every page, finds <input>/<select>/<textarea> fields, resolves a human label
 * for each, and lets you fill them via a floating panel. Each field has its own
 * fill button so YOU choose what to fill. There is also a "Fill all visible"
 * convenience button. Nothing is submitted automatically.
 */
(() => {
  const API = "http://127.0.0.1:8765";

  // ---------- field discovery ----------
  function visibleFields() {
    const sel = "input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select";
    return Array.from(document.querySelectorAll(sel)).filter(el => {
      if (el.disabled || el.readOnly) return false;
      const t = (el.type || "").toLowerCase();
      if (t === "file" || t === "radio") return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
  }

  function isVisible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function fileFields() {
    return Array.from(document.querySelectorAll('input[type="file"]')).filter(el => {
      return !el.disabled && !el.readOnly;
    });
  }

  function optionLabelForRadio(radio) {
    if (radio.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(radio.id)}"]`);
      if (lbl && lbl.innerText.trim()) return lbl.innerText.trim();
    }
    const wrapped = radio.closest("label");
    if (wrapped && wrapped.innerText.trim()) return wrapped.innerText.trim();
    const parent = radio.parentElement;
    if (parent && parent.innerText && parent.innerText.trim().length < 240) return parent.innerText.trim();
    return radio.value || radio.name || "choice";
  }

  function visibleRadioGroups() {
    const radios = Array.from(document.querySelectorAll('input[type="radio"]'))
      .filter(el => !el.disabled && !el.readOnly && isVisible(el));
    const grouped = new Map();
    radios.forEach((radio, idx) => {
      const key = radio.name || radio.getAttribute("data-testid") || `radio-${idx}`;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(radio);
    });
    return Array.from(grouped.values());
  }

  function radioGroupLabel(group) {
    const first = group[0];
    const fieldset = first.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend && legend.innerText.trim()) return legend.innerText.trim();
    }

    const optionTexts = new Set(group.map(optionLabelForRadio).map(t => t.replace(/\s+/g, " ").trim()).filter(Boolean));
    let node = first.parentElement;
    for (let depth = 0; node && depth < 6; depth += 1, node = node.parentElement) {
      const text = (node.innerText || "").replace(/\s+/g, " ").trim();
      if (text && text.length < 1800) {
        let question = text;
        optionTexts.forEach(opt => {
          question = question.replace(opt, " ");
        });
        question = question.replace(/\s+/g, " ").trim();
        if (question && question.length > 3 && question.length < 500) return question;
      }
    }
    const named = first.name || first.id || first.getAttribute("aria-label");
    return named ? named.replace(/[_\-]+/g, " ") : "Choice group";
  }

  function radioPromptLabel(group, display) {
    const options = group
      .map(optionLabelForRadio)
      .map(t => t.replace(/\s+/g, " ").trim())
      .filter(Boolean);
    const unique = Array.from(new Set(options)).slice(0, 12);
    if (!unique.length) return display;
    return `${display}\nOptions: ${unique.join(" | ")}\nAnswer with exactly one option when possible.`;
  }

  function selectPromptLabel(el, display) {
    const options = Array.from(el.options || [])
      .map(opt => (opt.text || opt.value || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .filter(t => !/^select|choose|pick$/i.test(t));
    const unique = Array.from(new Set(options)).slice(0, 20);
    if (!unique.length) return display;
    return `${display}\nOptions: ${unique.join(" | ")}\nAnswer with exactly one option when possible.`;
  }

  function uploadControls() {
    const controls = Array.from(document.querySelectorAll('button, [role="button"], a, div, span')).filter(el => {
      const text = [
        el.innerText,
        el.getAttribute("aria-label"),
        el.getAttribute("title"),
        el.getAttribute("data-automation-id"),
      ].filter(Boolean).join(" ").toLowerCase();
      if (!/\b(upload|attach|resume|cv|transcript|file|document)\b/.test(text)) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    return controls.slice(0, 8);
  }

  function labelFor(el) {
    // 1. <label for=id>
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.innerText.trim()) return l.innerText.trim();
    }
    // 2. wrapping <label>
    const parentLabel = el.closest("label");
    if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();
    // 3. aria-label / aria-labelledby
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label").trim();
    const lid = el.getAttribute("aria-labelledby");
    if (lid) {
      const text = lid.split(/\s+/)
        .map(id => document.getElementById(id))
        .filter(Boolean)
        .map(node => node.innerText || node.textContent || "")
        .join(" ")
        .trim();
      if (text) return text;
    }
    const did = el.getAttribute("aria-describedby");
    if (did) {
      const text = did.split(/\s+/)
        .map(id => document.getElementById(id))
        .filter(Boolean)
        .map(node => node.innerText || node.textContent || "")
        .join(" ")
        .trim();
      if (text && text.length < 160) return text;
    }
    // 4. placeholder
    if (el.placeholder) return el.placeholder.trim();
    // 5. login/account forms often expose intent via type/autocomplete only
    const t = (el.type || "").toLowerCase();
    const ac = (el.getAttribute("autocomplete") || "").toLowerCase();
    if (t === "password" || ac.includes("password")) return "password";
    if (t === "email" || ac === "username" || ac === "email") return "account email";
    if (t === "tel" || ac.includes("tel")) return "phone";
    if (ac.includes("given-name")) return "first name";
    if (ac.includes("family-name")) return "last name";
    if (ac.includes("name")) return "full name";
    if (ac.includes("address")) return "address";
    if (ac.includes("postal")) return "zip";
    if (ac.includes("country")) return "country";
    // 5. common name/id hints
    const attrText = [
      el.name,
      el.id,
      el.getAttribute("data-testid"),
      el.getAttribute("data-automation-id"),
      el.getAttribute("data-field"),
    ].filter(Boolean).join(" ").replace(/[_\-]+/g, " ").trim();
    if (attrText && attrText.length < 120) return attrText;
    // 6. preceding text node sibling
    const prev = el.previousElementSibling;
    if (prev && prev.innerText && prev.innerText.length < 120) return prev.innerText.trim();
    // 7. nearby upload container text
    const container = el.closest('[data-automation-id], [class], div, section, fieldset');
    if (container && container.innerText && container.innerText.trim().length < 180) {
      return container.innerText.trim();
    }
    // 8. name / id / accept attribute
    const base = (el.name || el.id || el.getAttribute("accept") || "field").replace(/[_\-.*\/]+/g, " ");
    return base.trim() || "field";
  }

  function displayLabel(label, idx = null) {
    const clean = String(label || "").replace(/\s+/g, " ").trim();
    if (clean && clean.toLowerCase() !== "field") return clean;
    return idx == null ? "Field" : `Field ${idx + 1}`;
  }

  function normChoice(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^\w\s]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function uploadKindForLabel(label) {
    const l = String(label || "").toLowerCase();
    if (/\b(transcript|academic record|grade report)\b/.test(l)) return "transcript";
    if (/\b(resume|cv|curriculum vitae)\b/.test(l)) return "resume";
    return null;
  }

  function dateLikeValue(rawValue, type) {
    const raw = String(rawValue || "").trim();
    const now = new Date();
    const yyyy = String(now.getFullYear());
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    if (type === "month") {
      const month = raw.match(/\b\d{4}-\d{2}\b/);
      return month ? month[0] : `${yyyy}-${mm}`;
    }
    if (type === "week") {
      const week = raw.match(/\b\d{4}-W\d{2}\b/i);
      return week ? week[0].toUpperCase() : "";
    }
    if (type === "time") {
      const time = raw.match(/\b\d{1,2}:\d{2}\b/);
      return time ? time[0].padStart(5, "0") : "09:00";
    }
    const iso = raw.match(/\b\d{4}-\d{2}-\d{2}\b/);
    return iso ? iso[0] : `${yyyy}-${mm}-${dd}`;
  }

  function setValue(el, value) {
    if (value == null) return;
    const t = (el.type || "").toLowerCase();
    if (t === "checkbox") {
      const v = String(value).trim().toLowerCase();
      const shouldCheck = ["yes", "true", "y", "1", "agree", "i agree"].some(x => v.includes(x));
      el.checked = shouldCheck;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    if (t === "radio") {
      const group = el.name
        ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`))
        : [el];
      setRadioGroupValue(group, value);
      return;
    }
    if (["date", "month", "week", "time", "datetime-local"].includes(t)) {
      const dateValue = dateLikeValue(value, t);
      if (!dateValue) return;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(el, dateValue);
      el.dispatchEvent(new Event("input",  { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    if (el.tagName === "SELECT") {
      const v = normChoice(value);
      for (const opt of el.options) {
        const optValue = normChoice(opt.value);
        const optText = normChoice(opt.text);
        if (optValue === v || optText === v || optText.includes(v) || v.includes(optText)) {
          el.value = opt.value;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return;
        }
      }
      return;
    }
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, String(value));
    el.dispatchEvent(new Event("input",  { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function setRadioGroupValue(group, value) {
    if (value == null) return false;
    const v = normChoice(value);
    if (!v) return false;
    const options = group.map(radio => ({
      radio,
      label: optionLabelForRadio(radio),
      value: radio.value || "",
    }));
    const match = options.find(o => {
      const label = normChoice(o.label);
      const val = normChoice(o.value);
      return val === v || label === v || label.includes(v) || v.includes(label);
    }) || options.find(o => {
      const label = normChoice(o.label);
      if (/green card|permanent residence|lawfully admitted/.test(v)) return /green card|permanent residence|lawfully admitted/.test(label);
      if (/sponsorship|visa|h-?1b/.test(v)) {
        // Visa/sponsorship answer - match "No" options for Green Card holder
        if (/^no\b|do.*not.*require|not.*require/.test(v)) return /^no\b|do.*not.*require|not.*require/.test(label);
        return /^no\b/.test(label);
      }
      if (/relocat|office|on.?site|five days|union square/.test(v)) {
        // Relocation/onsite answer - match "Yes" options
        if (/^yes\b/.test(v)) return /^yes\b|we.*re.*open|open to relocation/.test(label);
        return /^yes\b/.test(label);
      }
      if (/asian/.test(v)) return /\basian\b/.test(label);
      if (/male/.test(v) && !/female/.test(v)) return label === "male";
      if (/not a protected veteran|no.*protected veteran/.test(v)) return /not a protected veteran/.test(label);
      if (/no.*disability|don t have a disability|do not have a disability/.test(v)) return /^no\b.*disability/.test(label);
      if (/^yes\b/.test(v)) return /^yes\b/.test(label);
      if (/^no\b/.test(v)) return /^no\b/.test(label);
      return false;
    });
    if (!match) return false;
    match.radio.click();
    match.radio.checked = true;
    match.radio.dispatchEvent(new Event("input", { bubbles: true }));
    match.radio.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  // ---------- panel ----------
  let panel;
  let currentJobId = null;
  // SPA-form tracking: Workday/Greenhouse/etc multi-step apps don't trigger
  // window.load between steps. We watch the URL + DOM for new fields and
  // re-fill anything we haven't seen before.
  let initialApplicationHost = null;
  let spaWatchersInstalled = false;
  let forcedAutofillSession = false;
  const processedFields = new WeakSet();   // fields we've already called /answer for
  let refillTimer = null;
  let lastRefillAt = 0;
  const REFILL_DEBOUNCE_MS = 900;          // wait for DOM to settle after a change
  const REFILL_COOLDOWN_MS = 2500;         // never refill more than once per ~2.5s
  const REFILL_MIN_NEW_FIELDS = 2;         // need at least this many new fields to bother

  function buildPanel() {
    if (panel && document.body.contains(panel)) return panel;
    panel = document.createElement("div");
    panel.id = "job-agent-panel";
    panel.innerHTML = `
      <div class="ja-header">
        <span>Job Agent 0.1.4</span>
        <div>
          <button id="ja-refresh" title="Rescan fields">Refresh</button>
          <button id="ja-close" title="Close">Close</button>
        </div>
      </div>
      <div class="ja-status" id="ja-status">Connecting...</div>
      <div class="ja-job" id="ja-job"></div>
      <div class="ja-actions">
        <button id="ja-fill-all">Fill all visible</button>
        <button id="ja-mark">I applied to this</button>
      </div>
      <div class="ja-fields" id="ja-fields"></div>
    `;
    document.body.appendChild(panel);

    panel.querySelector("#ja-close").onclick = () => {
      panel.remove();
      panel = null;
    };
    panel.querySelector("#ja-refresh").onclick = renderFields;
    panel.querySelector("#ja-fill-all").onclick = fillAll;
    panel.querySelector("#ja-mark").onclick = markApplied;
    return panel;
  }

  async function pingServer() {
    try {
      const r = await fetch(`${API}/health`, { method: "GET" });
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  async function loadQueue() {
    try {
      const r = await fetch(`${API}/queue`);
      if (!r.ok) return [];
      return await r.json();
    } catch { return []; }
  }

  async function loadActiveApplication() {
    try {
      const r = await fetch(`${API}/active_application`);
      if (!r.ok) return null;
      const data = await r.json();
      return data.job || null;
    } catch {
      return null;
    }
  }

  async function loadDocuments() {
    try {
      const r = await fetch(`${API}/documents`);
      if (!r.ok) return {};
      const data = await r.json();
      return data.documents || {};
    } catch {
      return {};
    }
  }

  function getAutoFillSetting() {
    return new Promise(resolve => {
      try {
        chrome.storage.local.get({ jaAutoFillQueued: true }, data => resolve(Boolean(data.jaAutoFillQueued)));
      } catch {
        resolve(false);
      }
    });
  }

  function forceAutoFillForThisPage() {
    return location.hash.includes("jobagent_autofill=1");
  }

  function pickJobForUrl(queue) {
    const normalize = (value) => {
      try {
        const url = new URL(value);
        url.hash = "";
        return url.href.replace(/\/$/, "").toLowerCase();
      } catch {
        return String(value || "").split("#")[0].replace(/\/$/, "").toLowerCase();
      }
    };
    const u = normalize(location.href);
    // exact match first, then host match
    let m = queue.find(j => j.url && u.startsWith(normalize(j.url)));
    if (m) return m;
    try {
      const host = new URL(u).host;
      m = queue.find(j => j.url && new URL(j.url).host === host);
    } catch {}
    return m;
  }

  async function resolveJobForPage(queue) {
    const match = pickJobForUrl(queue);
    if (match) return match;
    return await loadActiveApplication();
  }

  async function renderFields() {
    const root = panel;
    if (!root || !document.body.contains(root)) return;
    const status = root.querySelector("#ja-status");
    const jobBox = root.querySelector("#ja-job");
    const list = root.querySelector("#ja-fields");
    if (!status || !jobBox || !list) return;
    list.innerHTML = "";

    const health = await pingServer();
    if (!health) {
      status.textContent = "❌ Backend not running. Start it: `python -m src.server`";
      return;
    }
    status.textContent = `Backend up - ${health.counts.queued} queued - ${health.counts.applied} applied`;

    const queue = await loadQueue();
    const match = await resolveJobForPage(queue);
    if (match) {
      currentJobId = match.job_id;
      if (!initialApplicationHost) initialApplicationHost = location.host;
      jobBox.innerHTML = `<b>${escapeHtml(match.company)}</b> - ${escapeHtml(match.title)} <i>${escapeHtml(match.location || "")}</i>`;
      installSpaWatchers();
    } else {
      currentJobId = null;
      jobBox.innerHTML = `<i>No matching queued job. Fill will still work generically.</i>`;
    }

    const fields = visibleFields();
    const radioGroups = visibleRadioGroups();
    const fileInputs = fileFields();
    const uploadButtons = uploadControls();
    const docs = await loadDocuments();
    if (!fields.length && !radioGroups.length && !fileInputs.length && !uploadButtons.length && !docs.resume && !docs.transcript) {
      list.innerHTML = "<div class='ja-empty'>No fillable fields detected on this page.</div>";
      return;
    }

    fields.forEach((el, idx) => {
      const lbl = displayLabel(labelFor(el), idx);
      const row = document.createElement("div");
      row.className = "ja-row";
      row.innerHTML = `
        <div class="ja-lbl" title="${escapeHtml(lbl)}">${escapeHtml(lbl)}</div>
        <button class="ja-fill" data-idx="${idx}">Fill</button>
      `;
      row.querySelector(".ja-fill").onclick = async (ev) => {
        ev.preventDefault();
        const btn = ev.currentTarget;
        btn.disabled = true; btn.textContent = "...";
        try {
          const promptLbl = el.tagName === "SELECT" ? selectPromptLabel(el, lbl) : lbl;
          const ans = await fetchAnswers([promptLbl]);
          if (ans && ans[promptLbl] != null) {
            setValue(el, ans[promptLbl]);
            processedFields.add(el);
            btn.textContent = "Done";
          } else {
            processedFields.add(el);
            btn.textContent = "Skip";
          }
        } catch (e) {
          btn.textContent = "Error";
        }
        setTimeout(() => { btn.disabled = false; btn.textContent = "Fill"; }, 1500);
      };
      list.appendChild(row);
    });

    radioGroups.forEach((group, idx) => {
      const lbl = displayLabel(radioGroupLabel(group), fields.length + idx);
      const row = document.createElement("div");
      row.className = "ja-row";
      row.innerHTML = `
        <div class="ja-lbl" title="${escapeHtml(lbl)}">${escapeHtml(lbl)}</div>
        <button class="ja-fill" data-idx="${idx}">Fill</button>
      `;
      row.querySelector(".ja-fill").onclick = async (ev) => {
        ev.preventDefault();
        const btn = ev.currentTarget;
        btn.disabled = true; btn.textContent = "...";
        try {
          const promptLbl = radioPromptLabel(group, lbl);
          const ans = await fetchAnswers([promptLbl]);
          if (ans && ans[promptLbl] != null && setRadioGroupValue(group, ans[promptLbl])) {
            group.forEach(el => processedFields.add(el));
            btn.textContent = "Done";
          } else {
            group.forEach(el => processedFields.add(el));
            btn.textContent = "Skip";
          }
        } catch (e) {
          btn.textContent = "Error";
        }
        setTimeout(() => { btn.disabled = false; btn.textContent = "Fill"; }, 1500);
      };
      list.appendChild(row);
    });

    const renderUploadRow = (label, clickTarget, defaultKind = null) => {
      const kind = uploadKindForLabel(label) || defaultKind;
      const isUnknownUpload = !kind;
      const path = kind ? docs[kind] : "";
      const hint = path
        ? `Choose manually: ${escapeHtml(path)}`
        : isUnknownUpload
          ? `Resume: ${escapeHtml(docs.resume || "not found")} Transcript: ${escapeHtml(docs.transcript || "not found")}`
          : "File upload detected. Browser security requires manual selection.";
      const row = document.createElement("div");
      row.className = "ja-row ja-file-row";
      row.innerHTML = `
        <div class="ja-lbl" title="${escapeHtml(label)}">
          ${escapeHtml(label)}
          <div class="ja-file-hint">${hint}</div>
        </div>
        <button class="ja-fill" type="button">Choose</button>
      `;
      row.querySelector(".ja-fill").onclick = (ev) => {
        ev.preventDefault();
        clickTarget.click();
      };
      list.appendChild(row);
    };

    fileInputs.forEach((el) => {
      const lbl = labelFor(el);
      renderUploadRow(lbl, el);
    });

    if (!fileInputs.length) {
      uploadButtons.forEach((el) => {
        const lbl = labelFor(el);
        renderUploadRow(lbl || "Upload document", el);
      });
    }

    if (!fileInputs.length && !uploadButtons.length && (docs.resume || docs.transcript)) {
      const row = document.createElement("div");
      row.className = "ja-row ja-file-row";
      row.innerHTML = `
        <div class="ja-lbl">
          Documents ready
          <div class="ja-file-hint">Resume: ${escapeHtml(docs.resume || "not found")} Transcript: ${escapeHtml(docs.transcript || "not found")}</div>
        </div>
      `;
      list.appendChild(row);
    }
  }

  async function fetchAnswers(labels) {
    const r = await fetch(`${API}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ labels, job_id: currentJobId }),
    });
    if (!r.ok) throw new Error("answer failed");
    const j = await r.json();
    return j.answers || {};
  }

  async function fillAll(options = {}) {
    const retry = options.retry !== false;
    const fields = visibleFields();
    const radioGroups = visibleRadioGroups();
    const fieldLabels = fields.map((el, idx) => displayLabel(labelFor(el), idx));
    const fieldPrompts = fields.map((el, idx) => {
      const lbl = fieldLabels[idx];
      return el.tagName === "SELECT" ? selectPromptLabel(el, lbl) : lbl;
    });
    const radioLabels = radioGroups.map((group, idx) => displayLabel(radioGroupLabel(group), fields.length + idx));
    const radioPrompts = radioGroups.map((group, idx) => radioPromptLabel(group, radioLabels[idx]));
    const labels = fieldPrompts.concat(radioPrompts);
    if (!labels.length) return 0;
    const ans = await fetchAnswers(labels);
    let filled = 0;
    fields.forEach((el, i) => {
      const v = ans[fieldPrompts[i]];
      if (v != null && String(v).trim() !== "") {
        setValue(el, v);
        filled += 1;
      }
      processedFields.add(el);  // mark every field we attempted, filled or not
    });
    radioGroups.forEach((group, i) => {
      const v = ans[radioPrompts[i]];
      if (v != null && String(v).trim() !== "" && setRadioGroupValue(group, v)) {
        filled += 1;
      }
      group.forEach(el => processedFields.add(el));
    });
    if (retry) {
      setTimeout(() => fillAll({ retry: false }).catch(() => {}), 900);
    }
    return filled;
  }

  function waitForFields(timeoutMs = 12000) {
    const started = Date.now();
    return new Promise(resolve => {
      const tick = () => {
        const fields = visibleFields();
        const radios = visibleRadioGroups();
        const uploads = fileFields();
        if (fields.length || radios.length || uploads.length || Date.now() - started > timeoutMs) {
          resolve(fields);
          return;
        }
        setTimeout(tick, 500);
      };
      tick();
    });
  }

  async function autoFillIfQueued() {
    const enabled = await getAutoFillSetting();
    const forced = forceAutoFillForThisPage();
    const health = await pingServer();
    if (!health) return;
    const queue = await loadQueue();
    const urlMatch = pickJobForUrl(queue);
    const activeMatch = urlMatch ? null : await loadActiveApplication();
    const match = urlMatch || activeMatch;
    if (!match) return;
    if (!enabled && !forced && !activeMatch) return;
    forcedAutofillSession = forced || Boolean(activeMatch);
    currentJobId = match.job_id;
    initialApplicationHost = location.host;
    buildPanel();
    await waitForFields();
    await renderFields();
    const filled = await fillAll();
    if (!panel || !document.body.contains(panel)) return;
    const status = panel.querySelector("#ja-status");
    if (status) {
      status.textContent = filled
        ? `Autofilled ${filled} visible fields. Review before submitting.`
        : "No visible fields were ready to autofill yet. Try Fill all visible.";
    }
    // Install SPA watchers so multi-step forms (Workday, Greenhouse, etc)
    // get re-filled when the next step renders without a full page reload.
    installSpaWatchers();
  }

  async function markApplied() {
    if (!currentJobId) {
      alert("No queued job matches this URL. Mark it from the dashboard instead.");
      return;
    }
    await fetch(`${API}/mark_applied`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: currentJobId, url: location.href }),
    });
    if (panel && document.body.contains(panel)) {
      const mark = panel.querySelector("#ja-mark");
      if (mark) mark.textContent = "Recorded";
    }
  }

  async function resolveCurrentJobId() {
    if (currentJobId) return currentJobId;
    const queue = await loadQueue();
    const match = await resolveJobForPage(queue);
    if (match) currentJobId = match.job_id;
    return currentJobId;
  }

  async function maybeMarkSubmitted() {
    const jobId = await resolveCurrentJobId();
    if (!jobId) return;
    setTimeout(async () => {
      try {
        await fetch(`${API}/mark_applied`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_id: jobId, url: location.href }),
        });
        if (panel && document.body.contains(panel)) {
          const mark = panel.querySelector("#ja-mark");
          const status = panel.querySelector("#ja-status");
          if (mark) mark.textContent = "Recorded";
          if (status) status.textContent = "Submission detected. Marked as applied.";
        }
      } catch {}
    }, 1500);
  }

  function looksLikeFinalSubmit(el) {
    if (!el) return false;
    const text = [
      el.innerText,
      el.value,
      el.getAttribute("aria-label"),
      el.getAttribute("title"),
    ].filter(Boolean).join(" ").toLowerCase();
    return /\b(submit|send|apply|complete)\b/.test(text)
      && !/\b(next|continue|save|review|upload|attach)\b/.test(text);
  }

  // ---------- SPA multi-step form support ----------
  // Workday, Greenhouse, Lever, Ashby etc. advance between application steps
  // via the History API without a full page reload, so window.load only fires
  // once. We watch for URL changes AND for new form fields appearing in the
  // DOM, then re-run fillAll on any field we haven't seen yet.

  function scheduleRefill(reason) {
    if (refillTimer) clearTimeout(refillTimer);
    refillTimer = setTimeout(() => {
      refillTimer = null;
      doRefill(reason).catch(() => {});
    }, REFILL_DEBOUNCE_MS);
  }

  async function doRefill(reason) {
    if (!currentJobId) return;
    const now = Date.now();
    if (now - lastRefillAt < REFILL_COOLDOWN_MS) {
      scheduleRefill(reason);  // re-arm if cooldown hit; new fields can wait
      return;
    }
    const enabled = await getAutoFillSetting();
    if (!enabled && !forceAutoFillForThisPage() && !forcedAutofillSession) return;

    const allFields = visibleFields();
    const radioGroups = visibleRadioGroups();
    const newFields = allFields.filter(el => !processedFields.has(el));
    const newRadioGroups = radioGroups.filter(group => group.some(el => !processedFields.has(el)));
    if (newFields.length + newRadioGroups.length < REFILL_MIN_NEW_FIELDS) return;

    lastRefillAt = now;
    const fieldLabels = newFields.map((el, idx) => displayLabel(labelFor(el), idx));
    const fieldPrompts = newFields.map((el, idx) => {
      const lbl = fieldLabels[idx];
      return el.tagName === "SELECT" ? selectPromptLabel(el, lbl) : lbl;
    });
    const radioLabels = newRadioGroups.map((group, idx) => displayLabel(radioGroupLabel(group), newFields.length + idx));
    const radioPrompts = newRadioGroups.map((group, idx) => radioPromptLabel(group, radioLabels[idx]));
    const labels = fieldPrompts.concat(radioPrompts);
    let filled = 0;
    try {
      const ans = await fetchAnswers(labels);
      newFields.forEach((el, i) => {
        const v = ans[fieldPrompts[i]];
        if (v != null && String(v).trim() !== "") {
          setValue(el, v);
          filled += 1;
        }
        processedFields.add(el);
      });
      newRadioGroups.forEach((group, i) => {
        const v = ans[radioPrompts[i]];
        if (v != null && String(v).trim() !== "" && setRadioGroupValue(group, v)) {
          filled += 1;
        }
        group.forEach(el => processedFields.add(el));
      });
    } catch (e) {
      return;
    }

    if (filled > 0 && panel && document.body.contains(panel)) {
      const status = panel.querySelector("#ja-status");
      if (status) {
        status.textContent = `Autofilled ${filled} new fields (${reason}). Review before submitting.`;
      }
      // Re-render the per-field list so the user can see the new fields
      renderFields().catch(() => {});
    }
  }

  function hookHistoryNavigation() {
    const origPush = history.pushState;
    const origReplace = history.replaceState;
    history.pushState = function () {
      const r = origPush.apply(this, arguments);
      scheduleRefill("nav");
      return r;
    };
    history.replaceState = function () {
      const r = origReplace.apply(this, arguments);
      scheduleRefill("nav");
      return r;
    };
    window.addEventListener("popstate", () => scheduleRefill("nav"));
    window.addEventListener("hashchange", () => scheduleRefill("nav"));
  }

  function watchDomForNewFields() {
    const obs = new MutationObserver((mutations) => {
      let mightHaveFields = false;
      for (const m of mutations) {
        for (const node of m.addedNodes) {
          if (node.nodeType !== 1) continue;  // element nodes only
          if (node.matches && node.matches("input, textarea, select")) {
            mightHaveFields = true; break;
          }
          if (node.querySelector && node.querySelector("input, textarea, select")) {
            mightHaveFields = true; break;
          }
        }
        if (mightHaveFields) break;
      }
      if (mightHaveFields) scheduleRefill("dom");
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  function installSpaWatchers() {
    if (spaWatchersInstalled) return;
    spaWatchersInstalled = true;
    hookHistoryNavigation();
    watchDomForNewFields();
  }

  // ---------- toggle from popup ----------
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "JA_TOGGLE") {
      if (panel && document.body.contains(panel)) {
        panel.remove();
        panel = null;
      } else {
        buildPanel();
        renderFields();
      }
    }
  });

  document.addEventListener("submit", () => {
    maybeMarkSubmitted();
  }, true);

  window.addEventListener("load", () => {
    setTimeout(autoFillIfQueued, 1200);
  });
  if (document.readyState === "complete" || document.readyState === "interactive") {
    setTimeout(autoFillIfQueued, 1200);
  }
})();
