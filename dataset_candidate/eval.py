"""
Reference evaluation script for the SAP Firefighter Log Compliance Reviewer challenge.

Usage:
    python eval.py --predictions <preds.jsonl> --labels <labels.jsonl>

Predictions and labels must each be JSONL files where each line is a record:
    {
      "session_id": "FF-...",
      "verdict": "PASS" | "REJECT" | "NEEDS_CORRECTION",
      "findings": [{"rule_id": "...", ...}, ...],
      ...
    }

Outputs:
    - Verdict-level confusion matrix and per-class precision/recall/F1
    - Macro-F1 across the three verdict classes
    - Per-rule precision/recall (matched on (session_id, rule_id) pairs)

Notes for candidates:
    - For self-evaluation during development, use this script with the
      train/labels.jsonl labels and your own predictions on the train set.
    - You will NOT receive labels for the test set. Submit predictions for
      both train and test; we will run this evaluator with the held-out labels.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


VERDICTS = ["PASS", "REJECT", "NEEDS_CORRECTION"]


def load_jsonl(path):
    records = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            records[r["session_id"]] = r
    return records


def verdict_metrics(preds, labels):
    """Returns confusion matrix, per-class P/R/F1, macro-F1, accuracy."""
    cm = {a: Counter() for a in VERDICTS}
    matched = 0
    total = 0
    for sid, label in labels.items():
        gold = label["verdict"]
        pred_record = preds.get(sid)
        pred = pred_record["verdict"] if pred_record else "MISSING"
        cm[gold][pred] += 1
        total += 1
        if gold == pred:
            matched += 1

    per_class = {}
    f1_sum = 0
    for cls in VERDICTS:
        tp = cm[cls][cls]
        fn = sum(v for k, v in cm[cls].items() if k != cls)
        fp = sum(cm[other][cls] for other in VERDICTS if other != cls)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_class[cls] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": tp + fn,
        }
        f1_sum += f1

    macro_f1 = f1_sum / len(VERDICTS)
    accuracy = matched / total if total else 0.0

    return {
        "confusion_matrix": {gold: dict(row) for gold, row in cm.items()},
        "per_class": per_class,
        "macro_f1": round(macro_f1, 3),
        "accuracy": round(accuracy, 3),
        "total": total,
    }


def rule_metrics(preds, labels):
    """Per-rule precision and recall, matched on (session_id, rule_id)."""
    gold_pairs = set()
    pred_pairs = set()
    rule_seen = set()

    for sid, label in labels.items():
        for f in label.get("findings", []):
            gold_pairs.add((sid, f["rule_id"]))
            rule_seen.add(f["rule_id"])

    for sid, pred in preds.items():
        for f in pred.get("findings", []):
            pred_pairs.add((sid, f["rule_id"]))
            rule_seen.add(f["rule_id"])

    by_rule = {}
    for rule in sorted(rule_seen):
        gold_r = {(s, r) for (s, r) in gold_pairs if r == rule}
        pred_r = {(s, r) for (s, r) in pred_pairs if r == rule}
        tp = len(gold_r & pred_r)
        fp = len(pred_r - gold_r)
        fn = len(gold_r - pred_r)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        by_rule[rule] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "tp": tp, "fp": fp, "fn": fn,
            "gold_support": len(gold_r),
        }
    return by_rule


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", required=True, help="JSONL of predictions")
    ap.add_argument("--labels", required=True, help="JSONL of gold labels")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of human format")
    args = ap.parse_args()

    preds = load_jsonl(args.predictions)
    labels = load_jsonl(args.labels)

    missing = set(labels) - set(preds)
    extra = set(preds) - set(labels)

    verdict = verdict_metrics(preds, labels)
    rules = rule_metrics(preds, labels)

    if args.json:
        print(json.dumps({
            "verdict": verdict,
            "rules": rules,
            "missing_predictions": sorted(missing),
            "unexpected_predictions": sorted(extra),
        }, indent=2))
        return

    # Human-readable
    print("=" * 60)
    print("VERDICT METRICS")
    print("=" * 60)
    print(f"Total sessions: {verdict['total']}")
    print(f"Accuracy: {verdict['accuracy']}")
    print(f"Macro F1: {verdict['macro_f1']}")
    print()
    print("Per-class:")
    for cls in VERDICTS:
        m = verdict["per_class"][cls]
        print(f"  {cls:20s}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}  (support={m['support']})")
    print()
    print("Confusion matrix (rows=gold, cols=pred):")
    cols = VERDICTS + ["MISSING"] if any("MISSING" in v for v in verdict["confusion_matrix"].values()) else VERDICTS
    print("  " + " " * 18 + " ".join(f"{c:>16}" for c in cols))
    for gold in VERDICTS:
        row = verdict["confusion_matrix"][gold]
        print(f"  {gold:>18} " + " ".join(f"{row.get(c, 0):>16}" for c in cols))
    print()
    print("=" * 60)
    print("PER-RULE METRICS")
    print("=" * 60)
    print(f"  {'rule':<10} {'P':>6} {'R':>6} {'F1':>6}  {'TP':>4} {'FP':>4} {'FN':>4}  support")
    for rule, m in rules.items():
        print(f"  {rule:<10} {m['precision']:>6.3f} {m['recall']:>6.3f} {m['f1']:>6.3f}  "
              f"{m['tp']:>4} {m['fp']:>4} {m['fn']:>4}  {m['gold_support']}")
    if missing:
        print()
        print(f"WARNING: {len(missing)} sessions missing from predictions: {sorted(missing)[:5]}...")
    if extra:
        print()
        print(f"NOTE: {len(extra)} predictions for sessions not in labels: {sorted(extra)[:5]}...")


if __name__ == "__main__":
    main()
