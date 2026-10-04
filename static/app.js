/* Merchant Recovery Console — ledger, playbook directions, tool audit. */
let customers = [];
let scenarios = {};
let selectedCustomer = null;

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
    btn.onclick = () => openModal(c.customer_id);
    const td = document.createElement("td");
    td.appendChild(btn);
    tr.appendChild(td);
    tr.onclick = (e) => { if (e.target !== btn) openDrawer(c.customer_id); };
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

async function liveCall() {
  const phone = document.getElementById("modal-phone").value.trim();
  const box = document.getElementById("modal-result");
  if (!phone) {
    box.textContent = "Enter your test number first (the allowlisted one).";
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
document.getElementById("btn-live-call").onclick = liveCall;
document.getElementById("btn-drawer-close").onclick = () =>
  document.getElementById("detail-drawer").classList.remove("open");

loadScenarios().then(loadCustomers);
