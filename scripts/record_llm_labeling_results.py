#!/usr/bin/env python3
"""Day 6, Phase 7 (step 2 of 2): record the LLM's semantic labels and compare
them against the withheld Day-3 `readable_name`.

Provenance, stated plainly so this is reproducible and auditable:

* **Model / assistant:** Claude (Anthropic), operating as the coding and
  analysis assistant for this session. No external LLM API was called; no
  API key exists in this repository and none was used.
* **Input:** exactly the compressed representations in
  `reports/day6/llm_labeling_inputs.json`, produced by
  `scripts/build_llm_labeling_inputs.py`. No raw event stream, no screenshot,
  and no part of the 2.8 GB dataset was provided.
* **Withheld:** the Day-3 `readable_name` for every process, so the label
  could not be read back from the input.
* **Prompt (paraphrased as issued):** "For each compressed process
  representation, give a concise process description, the likely business
  purpose, a confidence level, the evidence supporting the label, and any
  ambiguity or alternative interpretation. The identifiers contain Japanese;
  translate and interpret them."
* **Status of the output:** analyst assistance, NOT ground truth. The labels
  below were reviewed before being recorded, and the agreement judgement is
  a human reading of semantic equivalence, not an automatic metric.

The point of the comparison is not to score the LLM. It is to establish
whether compressed evidence is sufficient for a human-readable business
label, which is the gap between low-level operations and process
terminology.

Usage:
    python scripts/record_llm_labeling_results.py --day6-dir reports/day6 --day3-dir reports/day3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Labels produced by the assistant from the compressed representations only.
LLM_LABELS = {
    "system:財務会計システム": {
        "process_description": "Financial accounting system transaction entry and review",
        "likely_business_purpose": "Staff record or verify accounting entries in an internal "
                                   "browser-based finance system, with supporting documents "
                                   "consulted in Word.",
        "confidence": "high",
        "evidence": "The identifier 財務会計システム translates directly as 'financial accounting "
                    "system'. Browser-based (Microsoft Edge dominant), 125 executions across 4 "
                    "operators, median 14.3s, 68.1% manual events — short, repeated, "
                    "human-driven transactions rather than bulk automation.",
        "ambiguity": "The features cannot separate entry from review from approval. 10 variants "
                     "at 66.4% dominant share is the least concentrated of the three core "
                     "systems, so more than one sub-procedure is probably merged here.",
    },
    "system:HR人事給与システム": {
        "process_description": "HR/payroll record processing with reviewer comment entry",
        "likely_business_purpose": "Staff process HR and payroll items in an internal web system "
                                   "and record a processing note, reconciliation result, or "
                                   "approval/rejection comment against each item.",
        "confidence": "high",
        "evidence": "人事給与システム translates as 'HR/payroll system'. The four UI form "
                    "placeholders are decisive and each names a different task: 処理内容・確認コメント "
                    "('processing details / confirmation comment'), 照合結果・特記事項 "
                    "('reconciliation result / special notes'), 承認コメントまたは差戻し理由 "
                    "('approval comment or reason for return'), 処理内容・対応状況 "
                    "('processing details / handling status'). 77.05% dominant variant share "
                    "across 122 executions and 4 operators.",
        "ambiguity": "A single label understates the structure: the four distinct note fields "
                     "imply at least four sub-procedures sharing one system. One of them "
                     "(承認…または差戻し理由) is explicitly an approval/rejection decision, which is "
                     "judgement-bearing and should not be assumed automatable.",
    },
    "system:受発注在庫管理システム": {
        "process_description": "Order and inventory management transaction handling",
        "likely_business_purpose": "Staff enter or check orders and stock positions in an "
                                   "internal ordering/inventory system, occasionally noting "
                                   "details in Notepad.",
        "confidence": "high",
        "evidence": "受発注 means 'ordering / order receiving' and 在庫管理 means 'inventory "
                    "management'. 96 executions, 83.3% dominant variant — the most standardised "
                    "of the three core systems. Notepad in the application mix suggests "
                    "side-memo capture during the task.",
        "ambiguity": "Order entry versus stock adjustment versus lookup cannot be distinguished "
                     "from these aggregate features.",
    },
    "app:Microsoft Word::nyusha_checklist_shinsotsu_batch": {
        "process_description": "New-graduate onboarding checklist preparation in Word",
        "likely_business_purpose": "Preparing or completing the onboarding checklist for the "
                                   "new-graduate intake, cross-referencing employee and payroll "
                                   "records.",
        "confidence": "high",
        "evidence": "The romanised filename is explicit: 入社 (nyusha, 'joining the company'), "
                    "checklist, 新卒 (shinsotsu, 'new graduate'), batch. Word-dominant but "
                    "touches both the HR/payroll and financial systems, consistent with "
                    "cross-referencing. 91.9% dominant variant, only 37.5% manual events and a "
                    "short 8.4s median — largely templated work.",
        "ambiguity": "Cannot tell whether the operator is filling the checklist in or only "
                     "reviewing an already-prepared one.",
    },
    "app:Microsoft Word::keiyaku_kaijo_tetsuzuki": {
        "process_description": "Contract termination procedure document handling in Word",
        "likely_business_purpose": "Preparing or processing the paperwork for terminating or "
                                   "cancelling a contract, with reference to the order/inventory "
                                   "system.",
        "confidence": "high",
        "evidence": "契約解除 (keiyaku kaijo) is 'contract termination/cancellation' and 手続き "
                    "(tetsuzuki) is 'procedure'. Word-dominant with the order/inventory system "
                    "and three distinct browser ports in the mix.",
        "ambiguity": "Notably the LEAST standardised process in this set — 7 variants at only "
                     "44.8% dominant share. That is a strong signal the handling genuinely "
                     "varies case by case, so 'procedure' here is not a fixed script. Drafting, "
                     "reviewing and filing cannot be separated from these features.",
    },
    "app:Microsoft Word::gyomu_itaku_kyuuyo_kitei": {
        "process_description": "Outsourcing compensation regulations document reference in Word",
        "likely_business_purpose": "Consulting or maintaining the rules governing compensation "
                                   "for outsourced/contracted work.",
        "confidence": "medium-high",
        "evidence": "業務委託 (gyomu itaku) is 'outsourcing / contracting out', 給与 (kyuuyo) is "
                    "'salary/compensation', 規定 (kitei) is 'regulations'. 23 executions, 87.0% "
                    "dominant variant, 13.1s median, Word plus browser reference.",
        "ambiguity": "'Regulations' suggests a reference document being *consulted* rather than "
                     "a transaction being *executed*. If so, treating this as a business-process "
                     "execution may be a category error — it could be lookup activity attached "
                     "to some other process. Confidence is lowered for that reason.",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day6-dir", required=True, type=Path)
    ap.add_argument("--day3-dir", required=True, type=Path)
    args = ap.parse_args()

    inputs = json.loads(
        (args.day6_dir / "llm_labeling_inputs.json").read_text(encoding="utf-8")
    )
    profiles = json.loads(
        (args.day3_dir / "process_profiles_dataset_b.json").read_text(encoding="utf-8")
    )

    rows = []
    for item in inputs["items"]:
        pid = item["process_id"]
        llm = LLM_LABELS.get(pid)
        if llm is None:
            continue
        rows.append({
            "process_id": pid,
            "day3_readable_name_withheld_during_labeling": profiles[pid]["readable_name"],
            "llm_label": llm,
            "input_given_to_llm": item,
        })

    out = {
        "experiment": "Day-6 Phase 7 — LLM semantic labelling from compressed evidence",
        "provenance": {
            "assistant": "Claude (Anthropic), acting as this session's coding/analysis assistant",
            "external_api_called": False,
            "input_artifact": "reports/day6/llm_labeling_inputs.json",
            "raw_logs_sent": "none — compressed per-process summaries only",
            "screenshots_sent": "none",
            "day3_readable_name_withheld": True,
            "prompt_summary": "For each compressed process representation: concise process "
                              "description, likely business purpose, confidence, supporting "
                              "evidence, and ambiguity/alternative interpretation. Identifiers "
                              "contain Japanese; translate and interpret.",
        },
        "status": "Analyst assistance, NOT ground truth. Reviewed before recording. The "
                  "agreement judgement below is a human reading of semantic equivalence, not an "
                  "automatic metric.",
        "n_labeled": len(rows),
        "labels": rows,
    }
    path = args.day6_dir / "llm_labeling_results.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Recorded {len(rows)} LLM labels -> {path}\n", file=sys.stderr)
    for r in rows:
        print(f"  {r['process_id'][:46]:46s}", file=sys.stderr)
        print(f"     LLM   : {r['llm_label']['process_description']}", file=sys.stderr)
        print(f"     Day-3 : {r['day3_readable_name_withheld_during_labeling']}", file=sys.stderr)
        print(f"     conf  : {r['llm_label']['confidence']}", file=sys.stderr)


if __name__ == "__main__":
    main()
