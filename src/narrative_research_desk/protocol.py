import json
from hashlib import sha256
import re
from typing import Any

REQUIRED = {"hypothesis", "primary_metric", "baseline", "split", "cost_assumptions", "acceptance", "trial_budget"}

def freeze_protocol(protocol: dict[str, Any]) -> str:
    if not isinstance(protocol, dict) or not REQUIRED.issubset(protocol):
        raise ValueError("PROTOCOL_INCOMPLETE")
    budget = protocol["trial_budget"]
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError("INVALID_TRIAL_BUDGET")
    try:
        payload = json.dumps(protocol, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as error:
        raise ValueError("PROTOCOL_INVALID") from error
    return sha256(payload).hexdigest()

def validate_trial_ledger(cases: list[dict[str, Any]], protocol_hash: str) -> dict[str, Any]:
    if not isinstance(protocol_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", protocol_hash):
        return {"status": "REJECTED", "reason": "PROTOCOL_HASH_INVALID", "protocol_hash": protocol_hash}
    if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
        return {"status": "REJECTED", "reason": "TRIAL_LEDGER_INVALID", "protocol_hash": protocol_hash}
    if not cases:
        return {"status": "REJECTED", "reason": "TRIAL_LEDGER_EMPTY", "protocol_hash": protocol_hash}
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            return {"status": "REJECTED", "reason": "TRIAL_CASE_REUSED_OR_INVALID", "protocol_hash": protocol_hash}
        seen.add(case_id)
        if case.get("label_source") != "adjudicated":
            return {"status": "REJECTED", "reason": "GOLD_LABEL_NOT_ADJUDICATED", "protocol_hash": protocol_hash}
        split = case.get("split")
        if not isinstance(split, str) or split not in {"development", "holdout"}:
            return {"status": "REJECTED", "reason": "TRIAL_SPLIT_INVALID", "protocol_hash": protocol_hash}
        if split == "holdout":
            if "prompt_tuned" not in case:
                return {"status": "REJECTED", "reason": "HOLDOUT_TUNING_STATUS_UNKNOWN", "protocol_hash": protocol_hash}
            if not isinstance(case["prompt_tuned"], bool):
                return {"status": "REJECTED", "reason": "TRIAL_CASE_REUSED_OR_INVALID", "protocol_hash": protocol_hash}
            if case["prompt_tuned"]:
                return {"status": "REJECTED", "reason": "HOLDOUT_PROMPT_TUNED", "protocol_hash": protocol_hash}
    return {"status": "PASS", "protocol_hash": protocol_hash, "case_count": len(cases)}
