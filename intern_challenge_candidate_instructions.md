# Seargin AI/ML CoE — Internship Technical Challenge

## SAP Firefighter Log Compliance Reviewer

---

## 1. Background

Seargin's Application Managed Services (AMS) division runs SAP support for several Fortune 500 clients. Many of these clients are publicly traded and subject to **SOX (Sarbanes-Oxley)**, requiring strict controls over privileged access to production SAP systems.

When something breaks in production at 2:00 AM — a payment run fails, a master data record is corrupted, a transport gets stuck — a regular consultant doesn't have the authorizations to fix it. Instead, they request a **Firefighter ID (FFID)** through SAP GRC Emergency Access Management. This temporary, elevated-privilege account lets them do whatever is needed to resolve the incident.

Every keystroke during a firefighter session is logged. After the session ends, a **Firefighter Controller** (a designated reviewer, typically from a different team) must manually go through the logs and decide:

- Was the reason for emergency access legitimate?
- Did the firefighter only do what was necessary to resolve the stated issue?
- Were there any signs of abuse — out-of-scope changes, suspicious transactions, segregation of duties (SoD) violations, debug-and-replace, mass updates that should have gone through change management?

Today this review is done by hand. A senior controller spends **20–40 minutes per session**, and a typical large client generates **30–80 firefighter sessions per month**. The review backlog is constant. Mistakes happen — controllers rubber-stamp logs they didn't fully read, or flag false positives because they don't know the business context.

Your task is to build an **AI-assisted Firefighter Log Reviewer** that pre-screens each session and produces a structured verdict for the human controller, who then approves or overrides it.

This is a real problem. If the tool works, it goes into the AMS CoE toolkit and gets used on actual client engagements.

---

## 2. The Task

Build a system that ingests a single firefighter session log (provided as a structured file — see Dataset section) and produces:

### 2.1 Verdict
One of three labels:
- **PASS** — session is compliant; reason and actions are aligned, no red flags
- **REJECT** — clear violation; controller should reject and escalate
- **NEEDS_CORRECTION** — borderline or incomplete; controller should request additional information from the firefighter (e.g. missing justification, ambiguous transaction)

### 2.2 Structured Findings
For each compliance issue detected, return a finding object containing:
- `rule_id` — which compliance rule was triggered (you define the rule catalog)
- `severity` — `low` / `medium` / `high` / `critical`
- `location` — which log entry triggered it (line number, timestamp, or transaction code reference)
- `description` — what the issue is, in plain language
- `evidence` — the actual log entry text or values that caused the trigger

### 2.3 Suggested Correction
For sessions classified as `NEEDS_CORRECTION`, generate a draft message back to the firefighter explaining:
- What additional information or justification is needed
- Which specific actions in the log require clarification
- A suggested rewrite of the **reason code / justification field** if the original was vague (e.g. "fixed urgent issue" → "resolved failed payment run F110 for Company Code 1000 on 2026-04-15 at 03:14 UTC; root cause: blocked vendor 100234")

---

## 3. Compliance Rule Catalog (minimum baseline)

You are expected to implement **at least these rules**, plus identify and propose additional ones based on your analysis of the dataset. Originality and depth of the rule catalog are part of the evaluation.

**Baseline rules (must be detected):**

| Rule | Description | Typical Severity |
|------|-------------|------------------|
| R-001 | Reason code is empty, generic ("test", "fix", "asap"), or shorter than 20 characters | medium |
| R-002 | Reason code mentions one system/module but transactions touch a different one | high |
| R-003 | Session contains debug & replace activity (SM21 entries showing `/h` or value modification in debug) | critical |
| R-004 | Session contains direct table modification (SE16N edit mode, SM30 on sensitive tables) without a documented data fix request | high |
| R-005 | Session contains OS-level commands (SM49) | critical |
| R-006 | Transaction count or change-document count exceeds reasonable threshold for the stated reason (e.g. 200+ vendor master changes for "fix one vendor") | high |
| R-007 | Session occurred outside business hours AND reason does not indicate an actual emergency | medium |
| R-008 | Firefighter user and the original ticket requester are the same person (self-approval pattern) | high |
| R-009 | Session duration exceeds the auto-extend limit and there's no documented re-justification | medium |
| R-010 | Transactions executed include known SoD-conflict pairs (e.g. vendor master maintenance + payment run in same session) | critical |

You are encouraged to combine deterministic rule checks with semantic reasoning where appropriate — for example, judging whether the stated *reason* matches the *actions performed* in spirit, not just keywords.

---

## 4. Input Format

Each session is a single JSON file with this structure:

```json
{
  "session_id": "FF-2026-04-0823",
  "firefighter_id": "FF_FI_01",
  "firefighter_user": "JKOWALSKI",
  "controller": "MNOWAK",
  "system": "PRD-S4",
  "client": "ACME-DE",
  "start_time": "2026-04-15T03:14:22Z",
  "end_time": "2026-04-15T04:47:09Z",
  "reason_code": "Fixed urgent issue with payment run",
  "ticket_reference": "INC0045231",
  "transaction_log": [
    { "timestamp": "2026-04-15T03:15:01Z", "tcode": "F110", "description": "Automatic Payment Run" },
    { "timestamp": "2026-04-15T03:22:47Z", "tcode": "FBL1N", "description": "Vendor Line Item Display" }
  ],
  "change_log": [
    { "timestamp": "2026-04-15T03:31:12Z", "table": "LFA1", "key": "100234", "field": "SPERR", "old_value": "X", "new_value": "" }
  ],
  "system_log": [
    { "timestamp": "2026-04-15T03:28:00Z", "message": "Debug session started by JKOWALSKI", "type": "SM21" }
  ],
  "os_command_log": []
}
```

---

## 5. Required Output Format

A single JSON file per session:

```json
{
  "session_id": "FF-2026-04-0823",
  "verdict": "NEEDS_CORRECTION",
  "confidence": 0.78,
  "findings": [
    {
      "rule_id": "R-001",
      "severity": "medium",
      "location": "reason_code",
      "description": "Reason code is too generic and lacks specifics about which payment run, company code, or root cause.",
      "evidence": "Fixed urgent issue with payment run"
    },
    {
      "rule_id": "R-003",
      "severity": "critical",
      "location": "system_log[2]",
      "description": "Debug session started during firefighter window; debug & replace cannot be ruled out without further inspection.",
      "evidence": "2026-04-15T03:28:00Z — Debug session started by JKOWALSKI (SM21)"
    }
  ],
  "suggested_correction": {
    "message_to_firefighter": "Your firefighter session FF-2026-04-0823 requires additional information before it can be approved. Please clarify: (1) Which payment run (F110 run ID, Company Code) was affected? (2) What was the root cause? (3) Why was debug mode used during the session — please confirm no values were modified via debug & replace.",
    "suggested_reason_rewrite": "Resolved failed payment run F110 (run ID 20260415-001, Company Code 1000) due to blocked vendor 100234; unblocked vendor after confirming with AP team via INC0045231. Used debug only for inspection — no value modification."
  }
}
```

---

## 6. Deliverables

You must submit:

1. **Source code** in a Git repository (GitHub/GitLab) — Python preferred but not enforced
2. **A working backend** that processes a session file and returns the JSON verdict (CLI or REST endpoint)
3. **A simple UI** — a single web page where the controller can:
    - Upload a session JSON
    - See the verdict, findings (with the relevant log lines highlighted), and suggested correction
    - Click PASS / REJECT / SEND-BACK to record their final decision (this can save to a local file or in-memory store; no real auth needed)
4. **An evaluation harness** — run your system over the provided **labeled test set** and produce a confusion matrix + per-rule precision/recall. The eval script must be runnable with one command.
5. **A README** containing:
    - Architecture diagram (ASCII or a single image)
    - List of compliance rules implemented, with rationale for any rules added beyond the baseline
    - Description of which parts use deterministic logic vs. LLM, and **why**
    - Known failure modes — at least three honest examples of where your system gets it wrong
    - Cost estimate per session reviewed (token cost if LLM-based)
    - **What you would build next, given another week**

**Time budget:** 3–5 days of focused work. Please track and report actual hours spent.

**Tooling:** AI coding assistants (Cursor, Claude Code, Copilot, etc.) are explicitly **encouraged**. We don't care if you used AI to write code — we care that you understand what was written and made good decisions about architecture. Expect questions about both during the technical interview.

---

## 7. Evaluation Criteria

| Dimension | Weight | What we look for |
|---|---|---|
| Verdict accuracy on test set | 25% | F1 across the three classes; per-class recall matters more than overall accuracy |
| Finding quality | 20% | Are findings specific? Do they cite the right log lines? Are severities sensible? |
| Rule catalog depth | 15% | Did you go beyond the baseline 10 rules? Are added rules justified by patterns in the data? |
| Architecture & code quality | 15% | Separation of concerns, testability, sensible use of LLM vs. deterministic logic, error handling on malformed input |
| Suggested corrections quality | 10% | Are rewrites actually better than originals? Do they preserve the firefighter's intent? |
| Honesty about failure modes | 10% | The "what's broken" section in the README |
| UX of the controller UI | 5% | Is it usable? Does it highlight findings in context? |

**Bonus signals (none required, but noticed):**
- Handling of **adversarial inputs** (malformed JSON, timestamps in wrong timezones, log entries out of chronological order)
- Cost-aware LLM usage (caching, model routing — small model for triage, larger for borderline cases)
- A **"where I disagreed with the gold label"** appendix where you argue against specific test set labels you think are wrong, with reasoning

---

## 8. Submission & Interview

- Send us the link to your repository along with a short cover note (max one page) describing your approach.
- Your submission will be run against a private held-out test set during the technical interview.
- Be prepared to walk us through one case your system handles particularly well — and one where it fails. We are more interested in how you reason about the failures than in perfect accuracy.

Good luck.
