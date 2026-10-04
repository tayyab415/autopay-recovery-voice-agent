/* Merchant Recovery Console — ledger, playbook directions, tool audit. */
let customers = [];
let scenarios = {};
let selectedCustomer = null;
let phoneCustomer = null;
let smsSeen = 0;
let callTimer = null;

const CLOSED = new Set(["RESOLVED", "DO_NOT_CALL", "CANCELLATION_LOGGED", "DISPUTE_ESCALATED"]);
// Empty = same-origin (local serve). The S3-hosted page sets an absolute backend.
const API_BASE = (document.querySelector('meta[name="api-base"]') || {}).content || "";
const api = (path) => API_BASE + path;

async function loadCustomers() {
  const res = await fetch(api("/api/customers"));
  customers = await res.json();
  renderMetrics(customers);
  renderTable(customers);
}

async function loadScenarios() {
  const res = await fetch(api("/api/scenarios"));
  if (res.ok) scenarios = await res.json();
}

function renderMetrics(rows) {
  const outstanding = rows
    .filter((c) => c.status !== "RESOLVED")
    .reduce((s, c) => s + (c.amount_due || 0), 0);
  const inRecovery = rows.filter((c) => !CLOSED.has(c.status)).length;
  const resolved = rows.filter((c) => c.status === "RESOLVED").length;
  const rate = rows.length ? Math.round((resolved / rows.length) * 100) : 0;
  document.getElementById("metric-arr").textContent = "Rs." + outstanding.toLocaleString("en-IN");
  document.getElementById("metric-accounts").textContent = String(inRecovery);
  document.getElementById("metric-rate").textContent = rate + "%";
}

function renderTable(rows) {
  const tbody = document.querySelector("#customer-table tbody");
  tbody.innerHTML = "";
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${c.customer_id}</td><td>${c.name}</td>` +
      `<td><span class="badge">${c.failure_code}</span></td>` +
      `<td>Rs.${c.amount_due}</td>` +
      `<td><span class="badge ${c.status === "PENDING" ? "pending" : ""}">${c.status}</span></td>`;
    const btn = document.createElement("button");
    btn.className = "btn-primary";
    btn.textContent = "Trigger";
    btn.onclick = () => { openModal(c.customer_id); ringPhone(c); };
    const td = document.createElement("td");
    td.appendChild(btn);
    tr.appendChild(td);
    tr.onclick = (e) => { if (e.target !== btn) { ringPhone(c); openDrawer(c.customer_id); } };
    tbody.appendChild(tr);
  });
}

function openModal(customerId) {
  selectedCustomer = customers.find((c) => c.customer_id === customerId);
  document.getElementById("modal-customer").textContent =
    `${selectedCustomer.customer_id} - ${selectedCustomer.name} (${selectedCustomer.failure_code})`;
  const script = scenarios[selectedCustomer.customer_id];
  document.getElementById("modal-script").textContent = script ? `Persona line: ${script}` : "";
  document.getElementById("modal-result").textContent = "";
  document.getElementById("trigger-modal").classList.add("open");
}

function closeModal() { document.getElementById("trigger-modal").classList.remove("open"); }

async function runTool(tool) {
  const id = selectedCustomer.customer_id;
  const routes = {
    link: ["/api/tools/send-link", { customer_id: id, channel: "sms" }],
    reschedule: ["/api/tools/reschedule", { customer_id: id, target_date: plusDays(5) }],
    waive: ["/api/tools/waive-fee", { customer_id: id }],
    escalate: ["/api/tools/escalate-dispute", { customer_id: id, reason: "Raised from console" }],
  };
  const [url, body] = routes[tool];
  const res = await fetch(api(url), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  const box = document.getElementById("modal-result");
  if (!res.ok) {
    box.innerHTML = `Tool rejected (${res.status}): ${escapeHtml(data.detail || JSON.stringify(data))}`;
  } else if (data.checkout_url) {
    box.innerHTML = `Link sent. Customer pays here: <a href="${data.checkout_url}" target="_blank" rel="noopener">${escapeHtml(data.checkout_url)}</a>`;
  } else {
    box.textContent = JSON.stringify(data, null, 2);
  }
  await loadCustomers();
  selectedCustomer = customers.find((c) => c.customer_id === id);
  openDrawer(id);
}

function plusDays(n) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

async function runSimulation() {
  const speech = scenarios[selectedCustomer.customer_id] || "Can you send me a link to pay?";
  const res = await fetch(api("/api/simulate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_id: selectedCustomer.customer_id, user_speech: speech }),
  });
  const data = await res.json();
  document.getElementById("modal-result").textContent = JSON.stringify(data, null, 2);
  showTranscript(selectedCustomer.customer_id);
}

let browserCall = null;

function showPhonePanel(which) {
  document.getElementById("phone-idle").hidden = which !== "idle";
  document.getElementById("phone-incoming").hidden = which !== "incoming";
  document.getElementById("phone-active").hidden = which !== "active";
}

function ringPhone(customer) {
  phoneCustomer = customer;
  selectedCustomer = customer;
  smsSeen = 0;
  document.getElementById("phone-incoming-who").textContent =
    `${customer.name} · ${customer.failure_code} · Rs.${customer.amount_due}`;
  showPhonePanel("incoming");
  showPhoneTab("call");
  refreshSms();
}

function showPhoneTab(tab) {
  const call = tab === "call";
  document.getElementById("phone-call").hidden = !call;
  document.getElementById("phone-sms").hidden = call;
  document.getElementById("phone-tab-call").classList.toggle("on", call);
  document.getElementById("phone-tab-sms").classList.toggle("on", !call);
  if (!call) {
    smsSeen = Number(document.getElementById("sms-badge").dataset.count || 0);
    document.getElementById("sms-badge").hidden = true;
    document.getElementById("phone-sms-hint").hidden = true;
  }
}

function absUrl(url) {
  if (!url) return "";
  if (url.startsWith("http")) return url;
  return api(url);
}

async function refreshSms() {
  if (!phoneCustomer) return;
  const res = await fetch(api(`/api/customers/${phoneCustomer.customer_id}/messages`));
  if (!res.ok) return;
  const rows = await res.json();
  const thread = document.getElementById("sms-thread");
  const empty = document.getElementById("sms-empty");
  empty.hidden = rows.length > 0;
  thread.innerHTML = rows.map((m) => {
    const link = m.checkout_url
      ? `<p><a href="${escapeHtml(absUrl(m.checkout_url))}" target="_blank" rel="noopener">Open checkout</a></p>`
      : "";
    return `<div class="sms-bubble"><div class="sms-from">${escapeHtml(m.sender || "NexusCloud")} · ${escapeHtml((m.channel || "sms").toUpperCase())} · ${escapeHtml(m.at || "")}</div><p>${escapeHtml(m.body || "")}</p>${link}</div>`;
  }).join("");
  const badge = document.getElementById("sms-badge");
  badge.dataset.count = String(rows.length);
  const unread = Math.max(0, rows.length - smsSeen);
  const onMessages = !document.getElementById("phone-sms").hidden;
  badge.hidden = unread === 0 || onMessages;
  badge.textContent = String(unread);
  document.getElementById("phone-sms-hint").hidden = unread === 0 || document.getElementById("phone-active").hidden;
  if (onMessages) smsSeen = rows.length;
}

function startCallTimer() {
  clearInterval(callTimer);
  const started = Date.now();
  callTimer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const ss = String(elapsed % 60).padStart(2, "0");
    document.getElementById("phone-timer").textContent = `${mm}:${ss}`;
  }, 250);
}

function stopCallTimer() {
  clearInterval(callTimer);
  callTimer = null;
}

function browserCallError(err) {
  if (!err) return "Browser call failed.";
  if (err.code === "microphone_denied") return "Microphone permission was blocked. Allow the mic for this page and try again.";
  if (err.code === "at_capacity" && err.scope === "not_enabled") return "Browser calling is not turned on for this Bolna account yet.";
  if (err.code === "autoplay_blocked") return "The browser blocked audio. Click Talk in browser again.";
  return err.message || "Browser call failed.";
}

async function talkInBrowser() {
  const box = document.getElementById("modal-result");
  const hangup = document.getElementById("btn-hangup");
  if (typeof BolnaWebCall !== "function") {
    box.textContent = "The browser calling library did not load. Refresh and try again.";
    return;
  }
  const customer = selectedCustomer;
  box.textContent = "Connecting. Allow the microphone. Say hello when the call screen is up.";
  document.getElementById("phone-call-status").textContent = "Connecting. Allow the microphone, then say hello.";
  showPhonePanel("active");
  showPhoneTab("call");
  const call = new BolnaWebCall({
    sessionUrl: api("/api/calls/web-session"),
    userData: { customer_id: customer.customer_id },
  });
  browserCall = call;
  hangup.hidden = false;
  call.on("state-change", (state) => {
    if (state === "active") {
      box.textContent = "On the call. Say hello. The agent waits for that before it speaks.";
      document.getElementById("phone-call-status").textContent = "Say hello. The agent waits for that.";
      startCallTimer();
    }
  });
  call.on("error", (err) => {
    box.textContent = browserCallError(err);
    document.getElementById("phone-call-status").textContent = browserCallError(err);
    hangup.hidden = true;
    stopCallTimer();
    showPhonePanel(phoneCustomer ? "incoming" : "idle");
  });
  call.on("call-end", () => {
    hangup.hidden = true;
    stopCallTimer();
    showPhonePanel(phoneCustomer ? "incoming" : "idle");
    const runId = typeof call.getRunId === "function" ? call.getRunId() : "";
    box.textContent = runId ? "Call ended. Updating the account." : "Call ended.";
    document.getElementById("phone-call-status").textContent = "Call ended.";
    if (runId) pollCall(runId, customer.customer_id);
    else showTranscript(customer.customer_id);
  });
  try {
    await call.start();
  } catch (err) {
    hangup.hidden = true;
    stopCallTimer();
    box.textContent = browserCallError(err);
    document.getElementById("phone-call-status").textContent = browserCallError(err);
    showPhonePanel(phoneCustomer ? "incoming" : "idle");
  }
}

function hangUpBrowser() {
  if (browserCall && typeof browserCall.stop === "function") browserCall.stop();
  stopCallTimer();
}

function declineCall() {
  hangUpBrowser();
  showPhonePanel("idle");
  phoneCustomer = null;
}

async function liveCall() {
  const phone = document.getElementById("modal-phone").value.trim();
  const box = document.getElementById("modal-result");
  if (!phone) {
    box.textContent = "Type your number above in +91 format first.";
    return;
  }
  box.textContent = "Placing call… pick up your phone.";
  const res = await fetch(api("/api/calls/outbound"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_id: selectedCustomer.customer_id, phone }),
  });
  const data = await res.json();
  if (!res.ok) {
    box.textContent = `Call refused (${res.status}): ${data.detail || JSON.stringify(data)}`;
    return;
  }
  box.textContent = `Call queued. Execution ${data.execution_id} — talk to the agent, then watch the drawer fill in.`;
  pollCall(data.execution_id, selectedCustomer.customer_id);
}

async function pollCall(executionId, customerId) {
  const box = document.getElementById("modal-result");
  for (let i = 0; i < 18; i++) {
    await new Promise((r) => setTimeout(r, 10000));
    const res = await fetch(api(`/api/calls/${executionId}`));
    if (!res.ok) continue;
    const d = await res.json();
    box.textContent = `Call ${d.status} — ${d.conversation_duration || 0}s, cost ${d.total_cost ?? "?"}.` +
      (d.transcript ? `\n${d.transcript.slice(-500)}` : "\n(listening…)");
    if (d.status === "completed" && d.transcript) {
      await loadCustomers();
      openDrawer(customerId);
      break;
    }
  }
}

async function openDrawer(customerId) {
  const c = customers.find((x) => x.customer_id === customerId);
  const rec = c.recording_url ? `\nRecording: ${c.recording_url}` : "";
  const disposition = c.last_disposition ? `\nDisposition: ${c.last_disposition} (${c.recovery_probability})` : "";
  const nextTouch = c.next_touch_at ? `\nNext touch: ${c.next_touch_at}` : "";
  const ticket = c.support_ticket_id ? `\nTicket: ${c.support_ticket_id} paused until ${c.dunning_paused_until || "n/a"}` : "";
  const scheduled = c.scheduled_debit_date ? `\nDebit date: ${c.scheduled_debit_date}` : "";
  document.getElementById("transcript").textContent =
    `Customer: ${c.name} (${c.customer_id})\nFailure: ${c.failure_code} - ${c.failure_reason}\nStatus: ${c.status}${disposition}${nextTouch}${scheduled}${ticket}\nLast call: ${c.last_call_id || "none"}${rec}` +
    (c.disposition_notes ? `\n\n--- last call transcript ---\n${c.disposition_notes}` : "");
  let directions = "";
  try {
    const acct = await fetch(api("/api/tools/get-account"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id: customerId }),
    });
    if (acct.ok) {
      const data = await acct.json();
      directions = `${data.directions} Allowed: ${(data.allowed_actions || []).join(", ")}.`;
    }
  } catch (err) {
    directions = "";
  }
  document.getElementById("account-directions").textContent = directions;
  let audit = [];
  try {
    const res = await fetch(api(`/api/customers/${customerId}/audit`));
    if (res.ok) audit = await res.json();
  } catch (err) {
    audit = [];
  }
  const tl = document.getElementById("timeline");
  const rows = audit.map((a) => `<li>${a.at} ${a.tool}: ${a.result_status}. ${escapeHtml(a.message || "")}</li>`);
  tl.innerHTML = (rows.join("") || `<li>Status: ${c.status}</li><li>Last call: ${c.last_call_id || "none"}</li>`) +
    (c.recording_url ? `<li><audio controls src="${c.recording_url}"></audio></li>` : "");
  if (c.recording_url) {
    document.getElementById("audio-source").src = c.recording_url;
    document.getElementById("audio-player").load();
  }
  document.getElementById("detail-drawer").classList.add("open");
}

async function showTranscript(customerId) {
  await loadCustomers();
  openDrawer(customerId);
}

document.getElementById("btn-modal-close").onclick = closeModal;
document.getElementById("btn-tool-link").onclick = () => runTool("link");
document.getElementById("btn-tool-reschedule").onclick = () => runTool("reschedule");
document.getElementById("btn-tool-waive").onclick = () => runTool("waive");
document.getElementById("btn-tool-escalate").onclick = () => runTool("escalate");
document.getElementById("btn-run-simulation").onclick = runSimulation;
document.getElementById("btn-browser-call").onclick = talkInBrowser;
document.getElementById("btn-hangup").onclick = hangUpBrowser;
document.getElementById("btn-answer").onclick = () => { if (phoneCustomer) { selectedCustomer = phoneCustomer; talkInBrowser(); } };
document.getElementById("btn-decline").onclick = declineCall;
document.getElementById("btn-phone-hangup").onclick = hangUpBrowser;
document.getElementById("phone-tab-call").onclick = () => showPhoneTab("call");
document.getElementById("phone-tab-sms").onclick = () => { showPhoneTab("sms"); refreshSms(); };
document.getElementById("phone-sms-hint").onclick = () => showPhoneTab("sms");
document.getElementById("btn-live-call").onclick = liveCall;
setInterval(() => {
  document.getElementById("phone-clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  refreshSms();
}, 2000);
document.getElementById("btn-drawer-close").onclick = () =>
  document.getElementById("detail-drawer").classList.remove("open");

loadScenarios().then(loadCustomers);
