const OWNER = "jpndmatos";
const REPO = "3cket2brellaAPI";
const WORKFLOW_FILE = "sync.yml";
const API = "https://api.github.com";
const STORAGE_KEY = "threecket-control-room-pat";
const POLL_INTERVAL_MS = 5000;
const POLL_MAX_ATTEMPTS = 120;

const el = {
  pat: document.querySelector("#github-pat"),
  persistPat: document.querySelector("#persist-pat"),
  optPrune: document.querySelector("#opt-prune"),
  optDownload: document.querySelector("#opt-download"),
  optLimit: document.querySelector("#opt-limit"),
  btnPreview: document.querySelector("#btn-preview"),
  btnImport: document.querySelector("#btn-import"),
  btnClearLog: document.querySelector("#btn-clear-log"),
  btnRefresh: document.querySelector("#btn-refresh"),
  btnSaveSecrets: document.querySelector("#btn-save-secrets"),
  secretBrellaKey: document.querySelector("#secret-brella-key"),
  secretBrellaOrg: document.querySelector("#secret-brella-org"),
  secretBrellaEvent: document.querySelector("#secret-brella-event"),
  secretThreecketCookie: document.querySelector("#secret-threecket-cookie"),
  runStatus: document.querySelector("#run-status"),
  logConsole: document.querySelector("#log-console"),
  historyList: document.querySelector("#history-list"),
};

let polling = false;

// --- Logging ---

function log(message, level = "info") {
  const ts = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const prefix =
    level === "error" ? "[error]" : level === "success" ? "[ok]" : "[info]";
  const line = `${ts} ${prefix} ${message}`;
  const con = el.logConsole;
  con.textContent = con.textContent ? `${con.textContent}\n${line}` : line;
  con.scrollTop = con.scrollHeight;
}

// --- GitHub API helpers ---

function getHeaders() {
  const pat = el.pat.value.trim();
  if (!pat) throw new Error("GitHub PAT is required.");
  return {
    Authorization: `Bearer ${pat}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

async function ghFetch(path, opts = {}) {
  const url = path.startsWith("http") ? path : `${API}${path}`;
  const h = { ...getHeaders(), ...(opts.headers || {}) };
  const res = await fetch(url, { ...opts, headers: h });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`GitHub API ${res.status}: ${body.slice(0, 200)}`);
  }
  return res;
}

async function ghJSON(path) {
  return (await ghFetch(path)).json();
}

// --- Secrets management ---

async function encryptSecret(publicKey, value) {
  await sodium.ready;
  const keyBytes = sodium.from_base64(publicKey, sodium.base64_variants.ORIGINAL);
  const msgBytes = sodium.from_string(value);
  const encrypted = sodium.crypto_box_seal(msgBytes, keyBytes);
  return sodium.to_base64(encrypted, sodium.base64_variants.ORIGINAL);
}

async function saveSecrets() {
  const secrets = [];
  if (el.secretBrellaKey.value.trim())
    secrets.push(["BRELLA_API_KEY", el.secretBrellaKey.value.trim()]);
  if (el.secretBrellaOrg.value.trim())
    secrets.push(["BRELLA_ORG_ID", el.secretBrellaOrg.value.trim()]);
  if (el.secretBrellaEvent.value.trim())
    secrets.push(["BRELLA_EVENT_ID", el.secretBrellaEvent.value.trim()]);
  if (el.secretThreecketCookie.value.trim())
    secrets.push(["THREECKET_COOKIE", el.secretThreecketCookie.value.trim()]);

  if (!secrets.length) {
    log("No fields filled — nothing to save.", "error");
    return;
  }

  log(`Saving ${secrets.length} secret(s)...`);

  // Get repo public key for encryption
  const keyData = await ghJSON(
    `/repos/${OWNER}/${REPO}/actions/secrets/public-key`
  );

  for (const [name, value] of secrets) {
    const encryptedValue = await encryptSecret(keyData.key, value);
    await ghFetch(`/repos/${OWNER}/${REPO}/actions/secrets/${name}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        encrypted_value: encryptedValue,
        key_id: keyData.key_id,
      }),
    });
    log(`Saved ${name}.`, "success");
  }

  // Clear inputs after saving
  el.secretBrellaKey.value = "";
  el.secretBrellaOrg.value = "";
  el.secretBrellaEvent.value = "";
  el.secretThreecketCookie.value = "";

  log("All secrets saved to GitHub.", "success");
}

// --- Workflow dispatch ---

async function dispatchWorkflow(mode) {
  const inputs = {
    mode,
    prune_missing: String(el.optPrune.checked),
    download_csv: String(el.optDownload.checked),
    limit: String(el.optLimit.value || "0"),
  };

  log(`Dispatching workflow (${mode})...`);
  const beforeDispatch = new Date().toISOString();

  await ghFetch(
    `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs }),
    }
  );

  log("Workflow dispatched. Waiting for run to appear...");
  setStatus("Queued...", "pending");

  const runId = await findTriggeredRun(beforeDispatch);
  if (!runId) {
    throw new Error("Could not find the triggered workflow run.");
  }

  log(`Run #${runId} found. Polling for completion...`);
  await pollRunCompletion(runId);
}

async function findTriggeredRun(afterTimestamp) {
  for (let attempt = 0; attempt < 12; attempt++) {
    await sleep(2500);
    try {
      const data = await ghJSON(
        `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=5&branch=main`
      );
      const run = data.workflow_runs.find(
        (r) =>
          r.event === "workflow_dispatch" && r.created_at >= afterTimestamp
      );
      if (run) return run.id;
    } catch (err) {
      log(`Waiting for run... (${err.message})`, "error");
    }
  }
  return null;
}

// --- Polling ---

async function pollRunCompletion(runId) {
  polling = true;
  setBusy(true);

  for (let i = 0; i < POLL_MAX_ATTEMPTS && polling; i++) {
    try {
      const run = await ghJSON(
        `/repos/${OWNER}/${REPO}/actions/runs/${runId}`
      );

      if (run.status === "completed") {
        polling = false;
        const ok = run.conclusion === "success";
        setStatus(
          `Run #${runId} ${run.conclusion}`,
          ok ? "success" : "error"
        );
        log(
          `Run #${runId} completed: ${run.conclusion}.`,
          ok ? "success" : "error"
        );
        await fetchAndDisplayLogs(runId);
        setBusy(false);
        refreshHistory();
        return;
      }

      setStatus(`Run #${runId}: ${run.status}...`, "pending");
    } catch (err) {
      log(`Poll error: ${err.message}`, "error");
    }

    await sleep(POLL_INTERVAL_MS);
  }

  polling = false;
  setBusy(false);
  log("Polling timed out.", "error");
  setStatus("Polling timed out", "error");
}

// --- Log fetching ---

async function fetchAndDisplayLogs(runId) {
  log("Fetching run logs...");

  try {
    const jobsData = await ghJSON(
      `/repos/${OWNER}/${REPO}/actions/runs/${runId}/jobs`
    );

    if (!jobsData.jobs || jobsData.jobs.length === 0) {
      log("No jobs found for this run.", "error");
      return;
    }

    const jobId = jobsData.jobs[0].id;
    const res = await ghFetch(
      `/repos/${OWNER}/${REPO}/actions/jobs/${jobId}/logs`
    );
    const rawLog = await res.text();

    const cleaned = rawLog
      .replace(/\x1b\[[0-9;]*m/g, "")
      .replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z /gm, "");

    log("--- Run output start ---");
    const con = el.logConsole;
    con.textContent = con.textContent
      ? `${con.textContent}\n${cleaned}`
      : cleaned;
    con.textContent += "\n--- Run output end ---";
    con.scrollTop = con.scrollHeight;

    log("Logs loaded.", "success");
  } catch (err) {
    log(`Failed to fetch logs: ${err.message}`, "error");
  }
}

async function viewRunLogs(runId) {
  log(`Loading logs for run #${runId}...`);
  await fetchAndDisplayLogs(runId);
}

// --- History ---

async function refreshHistory() {
  try {
    const data = await ghJSON(
      `/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=10&branch=main`
    );
    renderHistory(data.workflow_runs || []);
  } catch (err) {
    el.historyList.innerHTML = `<p class="muted-text">Failed to load: ${err.message}</p>`;
  }
}

function renderHistory(runs) {
  if (!runs.length) {
    el.historyList.innerHTML = '<p class="muted-text">No runs found.</p>';
    return;
  }

  el.historyList.innerHTML = runs
    .map((r) => {
      const date = new Date(r.created_at).toLocaleString();
      const badge = conclusionBadge(r.status, r.conclusion);
      return `
        <div class="history-row">
          <span class="history-badge ${badge.cls}">${badge.text}</span>
          <span class="history-info">
            <strong>#${r.run_number}</strong> ${r.display_title || ""}
            <span class="history-date">${date}</span>
          </span>
          <button class="ghost-button history-log-btn" data-run-id="${r.id}" type="button">
            Logs
          </button>
        </div>`;
    })
    .join("");

  el.historyList.querySelectorAll(".history-log-btn").forEach((btn) => {
    btn.addEventListener("click", () => viewRunLogs(btn.dataset.runId));
  });
}

function conclusionBadge(status, conclusion) {
  if (status !== "completed") return { text: status, cls: "badge-pending" };
  if (conclusion === "success") return { text: "success", cls: "badge-success" };
  if (conclusion === "failure") return { text: "failure", cls: "badge-failure" };
  return { text: conclusion || status, cls: "badge-neutral" };
}

// --- UI helpers ---

function setStatus(text, level) {
  el.runStatus.textContent = text;
  el.runStatus.className = "status-strip";
  if (level) el.runStatus.classList.add(`status-${level}`);
}

function setBusy(isBusy) {
  el.btnPreview.disabled = isBusy;
  el.btnImport.disabled = isBusy;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- PAT persistence ---

function loadPat() {
  const saved = sessionStorage.getItem(STORAGE_KEY);
  if (saved) {
    el.pat.value = saved;
    el.persistPat.checked = true;
  }
}

function savePat() {
  if (el.persistPat.checked && el.pat.value.trim()) {
    sessionStorage.setItem(STORAGE_KEY, el.pat.value.trim());
  } else {
    sessionStorage.removeItem(STORAGE_KEY);
  }
}

// --- Event binding ---

function bindEvents() {
  el.btnPreview.addEventListener("click", async () => {
    setBusy(true);
    try {
      savePat();
      await dispatchWorkflow("preview");
    } catch (err) {
      log(`Preview failed: ${err.message}`, "error");
      setStatus("Failed", "error");
      setBusy(false);
    }
  });

  el.btnImport.addEventListener("click", async () => {
    if (!confirm("This will create, update, and delete participants in Brella. Continue?")) {
      return;
    }
    setBusy(true);
    try {
      savePat();
      await dispatchWorkflow("import");
    } catch (err) {
      log(`Import failed: ${err.message}`, "error");
      setStatus("Failed", "error");
      setBusy(false);
    }
  });

  el.btnSaveSecrets.addEventListener("click", async () => {
    el.btnSaveSecrets.disabled = true;
    try {
      savePat();
      await saveSecrets();
    } catch (err) {
      log(`Failed to save secrets: ${err.message}`, "error");
    } finally {
      el.btnSaveSecrets.disabled = false;
    }
  });

  el.btnClearLog.addEventListener("click", () => {
    el.logConsole.textContent = "";
  });

  el.btnRefresh.addEventListener("click", () => {
    savePat();
    refreshHistory();
  });

  el.pat.addEventListener("change", savePat);
}

// --- Init ---

function init() {
  loadPat();
  bindEvents();
  log("Dashboard ready.");

  if (el.pat.value.trim()) {
    refreshHistory();
  }
}

init();
