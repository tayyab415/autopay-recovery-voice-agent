/* Merchant Recovery Console — consumes GET /api/customers, POST /api/simulate, POST /api/tools/* */
let customers = [];
let selectedCustomer = null;

async function loadCustomers() {
  const res = await fetch("/api/customers");
  customers = await res.json();
  renderMetrics(customers);
  renderTable(customers);
}

function renderMetrics(rows) {
  const outstanding = rows.reduce((s, c) => s + (c.amount_due || 0), 0);
  const inRecovery = rows.filter((c) => c.status === "PENDING").length;
  const resolved = rows.filter((c) => !["PENDING"].includes(c.status)).length;
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
    `${selectedCustomer.customer_id} — ${selectedCustomer.name} (${selectedCustomer.failure_code})`;
  document.getElementById("modal-result").textContent = "";
  document.getElementById("trigger-modal").classList.add("open");
}

function closeModal() { document.getElementById("trigger-modal").classList.remove("open"); }

async function runSimulation() {
  const res = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_id: selectedCustomer.customer_id, user_speech: "Can you send me a link to pay?" }),
  });
  const data = await res.json();
  document.getElementById("modal-result").textContent = JSON.stringify(data, null, 2);
  showTranscript(selectedCustomer.customer_id, data);
}

async function liveCall() {
  const phone = document.getElementById("modal-phone").value.trim();
  if (!phone) {
    document.getElementById("modal-result").textContent = "Provide a test phone number for Live Call.";
    return;
  }
  document.getElementById("modal-result").textContent = "Live Call requires server-side Bolna credentials; use runner.py call --customer " + selectedCustomer.customer_id + " --phone " + phone;
}

function openDrawer(customerId) {
  const c = customers.find((x) => x.customer_id === customerId);
  document.getElementById("transcript").textContent =
    `Customer: ${c.name} (${c.customer_id})\nFailure: ${c.failure_code} — ${c.failure_reason}\nStatus: ${c.status}`;
  const tl = document.getElementById("timeline");
  tl.innerHTML = `<li>Status: ${c.status}</li><li>Last call: ${c.last_call_id || "none"}</li>`;
  document.getElementById("detail-drawer").classList.add("open");
}

function showTranscript(customerId, simData) {
  document.getElementById("transcript").textContent =
    `Agent: ${simData.agent_reply}\nTool: ${simData.tool_called}\nStatus: ${simData.final_status}`;
  const tl = document.getElementById("timeline");
  tl.innerHTML = `<li>${new Date().toISOString()} — ${simData.tool_called}</li>`;
  document.getElementById("detail-drawer").classList.add("open");
  loadCustomers();
}

document.getElementById("btn-modal-close").onclick = closeModal;
document.getElementById("btn-run-simulation").onclick = runSimulation;
document.getElementById("btn-live-call").onclick = liveCall;
document.getElementById("btn-drawer-close").onclick = () =>
  document.getElementById("detail-drawer").classList.remove("open");

loadCustomers();
