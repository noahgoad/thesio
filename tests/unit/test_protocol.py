import pytest
import json
from pathlib import Path
from narrative_research_desk.protocol import freeze_protocol, validate_trial_ledger
def test_protocol_freeze():
    p={"hypothesis":"test","primary_metric":"error_rate","baseline":"manual","split":"heldout","cost_assumptions":"recorded","acceptance":"predeclared","trial_budget":1}
    assert freeze_protocol(p)==freeze_protocol(dict(reversed(list(p.items()))));assert freeze_protocol({**p,"trial_budget":2})!=freeze_protocol(p)

@pytest.mark.parametrize("cases,digest,reason", [
    ([], "a" * 64, "TRIAL_LEDGER_EMPTY"),
    ([{"case_id": "1", "label_source": "adjudicated", "split": "train"}], "bad", "PROTOCOL_HASH_INVALID"),
    ([{"case_id": "1", "label_source": "adjudicated"}], "a" * 64, "TRIAL_SPLIT_INVALID"),
    ([{"case_id": "1", "label_source": "adjudicated", "split": []}], "a" * 64, "TRIAL_SPLIT_INVALID"),
    ([{"case_id": "  ", "label_source": "adjudicated", "split": "development"}], "a" * 64, "TRIAL_CASE_REUSED_OR_INVALID"),
    ([{"case_id": "1", "label_source": "model_output", "split": "holdout"}], "a" * 64, "GOLD_LABEL_NOT_ADJUDICATED"),
])
def test_trial_ledger_rejects_incomplete_or_malformed_evidence(cases, digest, reason):
    assert validate_trial_ledger(cases, digest)["reason"] == reason

def test_trial_ledger_requires_case_ids_unique_across_splits():
    result = validate_trial_ledger([
        {"case_id": "same", "label_source": "adjudicated", "split": "development"},
        {"case_id": "same", "label_source": "adjudicated", "split": "holdout"},
    ], "a" * 64)
    assert result["status"] == "REJECTED"
    assert result["reason"] == "TRIAL_CASE_REUSED_OR_INVALID"


@pytest.mark.parametrize("prompt_tuned,expected_reason", [
    (None, "HOLDOUT_TUNING_STATUS_UNKNOWN"),
    (True, "HOLDOUT_PROMPT_TUNED"),
])
def test_trial_ledger_rejects_holdout_without_explicit_untuned_attestation(prompt_tuned, expected_reason):
    case = {"case_id": "holdout-1", "label_source": "adjudicated", "split": "holdout"}
    if prompt_tuned is not None:
        case["prompt_tuned"] = prompt_tuned
    result = validate_trial_ledger([case], "a" * 64)
    assert result["status"] == "REJECTED"
    assert result["reason"] == expected_reason


def test_trial_ledger_accepts_holdout_only_with_explicit_false_tuning_attestation():
    result = validate_trial_ledger([{
        "case_id": "holdout-2", "label_source": "adjudicated", "split": "holdout", "prompt_tuned": False,
    }], "a" * 64)
    assert result["status"] == "PASS"
    assert result["case_count"] == 1

@pytest.mark.parametrize("cases", [None, {}, [None]])
def test_trial_ledger_handles_invalid_container_without_crashing(cases):
    result = validate_trial_ledger(cases, "a" * 64)
    assert result == {"status": "REJECTED", "reason": "TRIAL_LEDGER_INVALID", "protocol_hash": "a" * 64}

def test_r15_preregistration_locks_targets_and_discloses_unmet_pre_tuning_gate():
    root = Path(__file__).parents[2]
    if not (root / "evidence" / "protocol.json").is_file():
        pytest.skip("Private evaluation records are not distributed in the public repository")
    protocol = json.loads((root / "config" / "evaluation.json").read_text(encoding="utf-8"))
    digest = freeze_protocol(protocol["frozen_protocol"])
    assert len(digest) == 64
    recorded = json.loads((root / "evidence" / "protocol.json").read_text(encoding="utf-8"))
    assert recorded["frozen_protocol_sha256"] == digest
    assert recorded["pre_prompt_tuning_freeze"] is False
    assert protocol["dataset_requirements"] == {
        "minimum_facts": 100, "minimum_issuers": 8, "minimum_research_questions": 20,
        "split_disjoint_by": ["document_id", "issuer_id"],
    }
    assert protocol["targets"] == {
        "numeric_fact_accuracy_min": 0.98,
        "issuer_attribution_precision_min": 0.99,
        "fabricated_material_citations_max": 0,
    }
    assert protocol["pre_prompt_tuning_freeze"] is False
    assert protocol["evidence_status"] == "NOT_EVALUATED_NO_ADJUDICATED_CORPUS_OR_BASELINE"

def test_r15_acceptance_fixture_sets_expected_negative_results_independently():
    root = Path(__file__).parents[2]
    cases = json.loads((root / "tests" / "fixtures" / "acceptance" / "R15.json").read_text(encoding="utf-8"))
    assert {case["id"]: case["expected"] for case in cases["negative_cases"]} == {
        "model-generated-gold": "GOLD_LABEL_NOT_ADJUDICATED",
        "missing-split": "TRIAL_SPLIT_INVALID",
        "empty-ledger": "TRIAL_LEDGER_EMPTY",
        "invalid-protocol-hash": "PROTOCOL_HASH_INVALID",
    }
