const fileInput = document.querySelector("#sessionFile");
const reviewButton = document.querySelector("#reviewButton");
const useLlmR002 = document.querySelector("#useLlmR002");
const ollamaModel = document.querySelector("#ollamaModel");
const errorMessage = document.querySelector("#errorMessage");
const resultPanel = document.querySelector("#resultPanel");
const statusBadge = document.querySelector("#statusBadge");
const verdictValue = document.querySelector("#verdictValue");
const confidenceValue = document.querySelector("#confidenceValue");
const sessionIdValue = document.querySelector("#sessionIdValue");
const reasonValue = document.querySelector("#reasonValue");
const ticketValue = document.querySelector("#ticketValue");
const findingsCount = document.querySelector("#findingsCount");
const findingsList = document.querySelector("#findingsList");
const correctionContent = document.querySelector("#correctionContent");
const logsContent = document.querySelector("#logsContent");
const decisionComment = document.querySelector("#decisionComment");
const decisionStatus = document.querySelector("#decisionStatus");

let currentSession = null;
let currentReview = null;

reviewButton.addEventListener("click", reviewSelectedFile);

document.querySelectorAll("[data-decision]").forEach((button) => {
  button.addEventListener("click", () => recordDecision(button.dataset.decision));
});

async function reviewSelectedFile() {
  clearError();
  decisionStatus.textContent = "";

  const file = fileInput.files[0];
  if (!file) {
    showError("Choose a session JSON file first.");
    return;
  }

  let payload;
  try {
    payload = JSON.parse(await file.text());
  } catch {
    showError("Selected file is not valid JSON.");
    return;
  }

  try {
    reviewButton.disabled = true;
    currentSession = payload;
    const params = new URLSearchParams({
      use_llm_r002: useLlmR002.checked ? "true" : "false",
    });
    if (ollamaModel.value.trim()) {
      params.set("ollama_model", ollamaModel.value.trim());
    }

    const response = await fetch(`/review?${params.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Review failed.");
    }

    currentReview = await response.json();
    renderReview(currentReview, currentSession);
  } catch (error) {
    showError(error.message);
  } finally {
    reviewButton.disabled = false;
  }
}

function renderReview(review, session) {
  resultPanel.classList.remove("hidden");
  statusBadge.textContent = review.verdict;
  statusBadge.className = `status-badge ${review.verdict.toLowerCase().replace("_", "-")}`;
  verdictValue.textContent = review.verdict;
  verdictValue.className = review.verdict.toLowerCase().replace("_", "-");
  confidenceValue.textContent = Number(review.confidence).toFixed(2);
  sessionIdValue.textContent = review.session_id;
  reasonValue.textContent = session.reason_code || "-";
  ticketValue.textContent = session.ticket_reference || "-";

  renderFindings(review.findings || []);
  renderCorrection(review.suggested_correction);
  renderLogs(session);
}

function renderFindings(findings) {
  findingsCount.textContent = String(findings.length);
  findingsList.innerHTML = "";

  if (findings.length === 0) {
    findingsList.innerHTML = '<p class="empty-state">No compliance issues detected.</p>';
    return;
  }

  for (const finding of findings) {
    const item = document.createElement("article");
    item.className = "finding-item";
    item.innerHTML = `
      <div class="finding-header">
        <strong>${escapeHtml(finding.rule_id)}</strong>
        <span class="severity ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</span>
      </div>
      <p>${escapeHtml(finding.description)}</p>
      <dl>
        <div><dt>Location</dt><dd>${escapeHtml(finding.location)}</dd></div>
        <div><dt>Evidence</dt><dd>${escapeHtml(finding.evidence)}</dd></div>
      </dl>
    `;
    findingsList.appendChild(item);
  }
}

function renderCorrection(correction) {
  if (!correction) {
    correctionContent.innerHTML = '<p class="empty-state">No correction request needed.</p>';
    return;
  }

  correctionContent.innerHTML = `
    <h3>Message to firefighter</h3>
    <p>${escapeHtml(correction.message_to_firefighter)}</p>
    <h3>Suggested reason rewrite</h3>
    <p>${escapeHtml(correction.suggested_reason_rewrite || "-")}</p>
  `;
}

function renderLogs(session) {
  const sections = [
    ["Transaction Log", session.transaction_log || []],
    ["Change Log", session.change_log || []],
    ["System Log", session.system_log || []],
    ["OS Command Log", session.os_command_log || []],
  ];

  logsContent.innerHTML = "";
  for (const [title, entries] of sections) {
    const block = document.createElement("details");
    block.open = title === "Transaction Log";
    block.innerHTML = `
      <summary>${title} (${entries.length})</summary>
      <pre>${escapeHtml(JSON.stringify(entries, null, 2))}</pre>
    `;
    logsContent.appendChild(block);
  }
}

async function recordDecision(decision) {
  clearError();
  decisionStatus.textContent = "";

  if (!currentReview) {
    showError("Review a session before recording a controller decision.");
    return;
  }

  try {
    const response = await fetch("/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentReview.session_id,
        decision,
        comment: decisionComment.value || null,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Decision could not be recorded.");
    }

    decisionStatus.textContent = `Recorded ${decision}.`;
  } catch (error) {
    showError(error.message);
  }
}

function showError(message) {
  errorMessage.textContent = message;
}

function clearError() {
  errorMessage.textContent = "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
