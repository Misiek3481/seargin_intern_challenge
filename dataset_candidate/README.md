# Dataset — SAP Firefighter Log Compliance Reviewer

This dataset accompanies the internship technical challenge. It contains synthetic but realistic SAP firefighter session logs, modeled after real SAP GRC Emergency Access Management output.

## Structure

```
dataset/
├── train/
│   ├── sessions/           # 50 session JSON files (FF-TRAIN-0001.json ... FF-TRAIN-0050.json)
│   └── labels.jsonl        # gold labels for the train set (one record per line)
├── test/
│   └── sessions/           # 25 session JSON files (FF-TEST-0001.json ... FF-TEST-0025.json)
│                           # NO labels are provided for the test set
├── eval.py                 # reference evaluation script
└── README.md               # this file
```

## Session JSON format

Each `sessions/FF-XXXX.json` follows this shape:

```json
{
  "session_id": "FF-TRAIN-0001",
  "firefighter_id": "FF_FI_01",
  "firefighter_user": "JKOWALSKI",
  "controller": "RGRC",
  "system": "PRD-S4",
  "client": "ACME-DE",
  "start_time": "2026-04-15T03:14:22Z",
  "end_time": "2026-04-15T04:47:09Z",
  "reason_code": "...",
  "ticket_reference": "INC0045231",
  "ticket_requester": "JKOWALSKI",     // optional, present in some sessions
  "alert_source": "MONITORING_AUTO",   // optional, present in some sessions
  "transaction_log": [ {timestamp, tcode, description}, ... ],
  "change_log":      [ {timestamp, table, key, field, old_value, new_value}, ... ],
  "system_log":      [ {timestamp, message, type}, ... ],
  "os_command_log":  [ {timestamp, command, parameters, executed_by}, ... ]
}
```

All timestamps are ISO 8601 UTC. Logs within each list are sorted ascending by timestamp.

## Label format (train set)

`train/labels.jsonl` — one JSON object per line:

```json
{
  "session_id": "FF-TRAIN-0001",
  "verdict": "PASS" | "REJECT" | "NEEDS_CORRECTION",
  "findings": [
    {
      "rule_id": "R-XXX",
      "severity": "low" | "medium" | "high" | "critical",
      "location": "string indicating where in the session the issue was found",
      "description": "human-readable explanation",
      "evidence": "actual log content or value that triggered the rule"
    },
    ...
  ],
  "suggested_correction": null | {
    "message_to_firefighter": "...",
    "suggested_reason_rewrite": null | "..."
  }
}
```

## How to use the eval script

After running your system on any set of sessions, write your predictions in the same JSONL format used by `labels.jsonl` (same keys, same shape). Then:

```bash
python3 eval.py --predictions your_predictions.jsonl --labels train/labels.jsonl
```

This will print verdict-level metrics (per-class precision/recall/F1, macro-F1, confusion matrix) and per-rule precision/recall (matched on `(session_id, rule_id)` pairs).

For final submission, run your system on **both** the train and the test set, and provide both prediction files. We will run `eval.py` against your predictions using the held-out test labels.

## Notes

- The dataset is synthetic. Names, vendor numbers, IBANs, and ticket references are not real.
- Firefighter ID naming follows a typical convention: `FF_<MODULE>_<NN>` (e.g., `FF_FI_01` for finance firefighter 1).
- The dataset includes a mix of clear-cut and borderline cases. Some sessions are deliberately designed to look one way on a quick keyword scan and a different way on careful inspection — this is intentional.
- You are welcome (and encouraged) to disagree with specific labels in the train set if you believe a different verdict is justified. Document any such disagreements in your README; they are a positive signal, not a negative one.
- The test set may include rule violations or scenario types not covered in the train set. Your system should handle the baseline rule catalog from the brief plus any additional rules you justify, regardless of which examples appear where.
