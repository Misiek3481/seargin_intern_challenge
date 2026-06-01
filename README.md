# SAP Firefighter Log Compliance Reviewer

An AI-assisted system designed to automatically analyze and evaluate SAP Firefighter (EAM) session logs. The tool processes JSON session files, applies a set of deterministic heuristics alongside targeted LLM evaluation, and outputs a structured verdict (`PASS`, `REJECT`, `NEEDS_CORRECTION`) along with findings and suggested messages for the firefighter.

---

## 1. Architecture Diagram

The system architecture is based on a pipeline that separates parsing, feature extraction, rule evaluation, and verdict aggregation.

    [Session JSON File] 
            │
            ▼
    (SessionParser) ──► Validates structure, types, and normalizes log fields
            │
            ▼
    (FeatureExtractor) ──► Aggregates session features (e.g., TCodes, change counts, duration)
            │
            ▼
    (RuleEngine) ─────► Deterministic rules (R-001, R-003, ..., R-013)
            │     └───► [OllamaR002Assessor] ──► Semantic validation via local LLM
            ▼
    (VerdictAggregator) ──► Calculates final verdict and confidence score
            │
            ▼
    (CorrectionBuilder) ──► Generates feedback messages (for NEEDS_CORRECTION)
            │             Note: LlmCorrectionBuilder is currently an unimplemented template shape.
            ▼
    [ReviewResult] ────► API (FastAPI) / CLI / Frontend (Web UI)

---

## 2. Compliance Rule Catalog

The system implements the 10 baseline rules and introduces 3 additional rules based on historical security gaps. 

**Baseline Rules:**
*   **R-001**: Reason code is empty, generic, or too short (`medium`).
*   **R-002**: Mismatch between the stated reason and actual transactions performed (`high`).
*   **R-003**: Debug & replace activity detected (`critical`).
*   **R-004**: Direct table modification without documented data fix approval (`high`).
*   **R-005**: OS-level commands executed (`critical`).
*   **R-006**: Excessive change-document volume contradicting the reason (`high`).
*   **R-007**: After-hours session without an emergency justification (`medium`).
*   **R-008**: Self-approval pattern (firefighter is the ticket requester) (`high`).
*   **R-009**: Session duration exceeds auto-extend limits without re-justification (`medium`).
*   **R-010**: SoD conflict (e.g., vendor master maintenance + payment run) (`critical`).

**Additional Rules & Rationale:**
*   **R-011: Missing Ticket For Production Change** (`medium`). *Rationale:* A firefighter session making physical production data changes must have a ticket reference for strict audit traceability. Read-only sessions missing a ticket trigger a lower severity warning.
*   **R-012: Log Outside Firefighter Window** (`high`). *Rationale:* Flags log entries with timestamps outside the declared session window (accounting for minor clock skew) to detect anomalies or potential manipulation of system logs.
*   **R-013: Repeated Auth Failures Before Sensitive Change** (`high`). *Rationale:* Identifies trial-and-error privilege escalation. Multiple `SU53` authorization failures immediately preceding a sensitive table change often indicate the user lacked proper authorization planning before attempting the change.

---

## 3. Deterministic Logic vs. LLM

The architecture relies on a **hybrid approach** to balance reliability, speed, and intelligence:

*   **Deterministic Logic:** Used for 12 out of 13 rules. Tasks like counting changes, checking for specific TCodes (e.g., `SM49`, `SE16N`), math operations on timestamps, and SoD conflict detection are 100% reliable, fast, and computationally cheap when done in standard Python code. LLMs struggle with precise counting and strict dictionary matching, making deterministic code the superior choice here.
*   **LLM (`OllamaR002Assessor`):** Targeted exclusively at R-002 to evaluate semantic mismatches between the text in the `reason_code` and the actions performed. It is placed behind a deterministic "pre-filter" - the LLM is only invoked if the actions touch sensitive scopes (like FI/MM) but the reason code is ambiguous or suggests a different scope. 

---

## 4. Known Failure Modes

Based on the evaluation harness running against the 50-session test set (yielding a Macro F1 of 0.914 and overall Accuracy of 0.92), the system exhibits the following failure modes:

1.  **R-007 (After Hours) False Positives (Precision: 0.625, FP: 6):** 
    The deterministic heuristic relies on a hardcoded list of emergency terms (e.g., "urgent", "outage"). If a firefighter describes a valid after-hours emergency without using those specific keywords (e.g., "server crashed"), the system fails to recognize it and incorrectly flags the session.
2.  **R-001 (Weak Reason) False Negatives (Recall: 0.643, FN: 5):**
    The system assumes a reason is sufficient if it exceeds 20 characters and avoids a basic blacklist ("test", "fix"). Because of this, verbose but meaningless descriptions (e.g., "Performed routine checks on the system as requested") bypass the heuristic, missing what a human controller would rightfully flag as inadequate.
3.  **`NEEDS_CORRECTION` Misclassified as `REJECT` (3 occurrences in Confusion Matrix):**
    The `VerdictAggregator` dictates that any "high" or "critical" severity finding instantly forces a `REJECT` verdict. In borderline scenarios, the human gold label preferred `NEEDS_CORRECTION` to ask for more context, but the system's rigid aggregation aggressively escalated the verdict to `REJECT`.

---

## 5. Cost Estimate

*   **Local Deployment (Current Setup):** Utilizing local models via Ollama (e.g., `llama3.1`), the token cost per session reviewed is **$0.00** (excluding hardware/electricity).
*   **Cloud API Equivalent:** The R-002 prompt consumes approximately 300-400 input tokens and generates around 50 output tokens. Using a cost-effective model like GPT-4o-mini, the cost would be less than **$0.0001 per LLM invocation**. Since the LLM is hidden behind a deterministic pre-filter and only triggers on ambiguous sessions, the total operating cost across thousands of sessions remains negligible.

---

## 6. What I would build next, given another week

1.  **Improve R-007 & Understand Firefighter Operations:** I would deeply analyze the root causes of the false positives in R-007 and spend time gaining a better, more practical understanding of how firefighters actually operate day-to-day to create more accurate heuristics.
2.  **Enhance R-001 with an LLM:** The current keyword-based logic for R-001 is too naive. I would integrate an LLM to accurately and semantically evaluate whether the reason code provides sufficient business context and justification.
3.  **Investigate `NEEDS_CORRECTION` Misclassifications:** I would conduct a thorough investigation into the rule logic to understand exactly why certain borderline cases that should logically be flagged as `NEEDS_CORRECTION` are being too aggressively classified as `REJECT`.

## 7. How to Run & Execution Guide

This guide assumes that you have already configured your virtual environment (`.venv`) and installed all the necessary dependencies from `requirements.txt`.

### 7.1 Running Evaluation without LLM (Heuristic Only)
To run the evaluation script using purely deterministic rule checking, execute the following command:
```bash
python dataset_candidate/eval.py --predictions predictions.jsonl --labels dataset_candidate/train/labels.jsonl
```

### 7.2 Running Evaluation with LLM (Ollama Fallback)
To enable the semantic analysis via an LLM fallback for rule R-002, you need to set up Ollama locally.

#### Prerequisites & Environment Setup (Windows):
1. Download and install Ollama from the official website: https://ollama.com/download.
2. Open **PowerShell** and download the required model using the following command:
```powershell
   ollama pull llama3.1
   ```
3. Verify that the model is successfully installed and available:
```powershell
   ollama list
   ```

#### Running the CLI Pipeline:
Once the local Ollama service is up and running, trigger the directory review batch processor using the CLI module:
```bash
python -m sap_ff_reviewer.cli review-dir dataset_candidate\train\sessions --output predictions.jsonl --use-r002-llm --ollama-model llama3.1:latest
```

### 7.3 Running Automated Tests
The test suite validates features, parsers, and specific rule limits. You can execute all unit and integration tests using `pytest`:
```bash
pytest
```

---

## 8. Controller UI Decisions Storage

When a designated reviewer uses the Frontend web companion interface to record a final decision (`PASS` / `REJECT` / `SEND_BACK`), the data is transmitted to the backend API via the `/decision` endpoint. 

All final human controller verdicts, timestamps, and contextual comments are permanently appended to a structured local file in the project's root folder:
* **Storage Location:** `decisions.jsonl`