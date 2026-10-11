import json
from hashlib import sha256

import pytest

from narrative_research_desk.assessment import CATEGORY_BY_REQUIREMENT, GATE_REQUIREMENTS, completion, review_scope_sha256


def write_ref(root, rid):
    path = root / f"{rid}.json"
    path.write_text(json.dumps({"requirement_id": rid, "status": "VERIFIED"}), encoding="utf-8")
    return {"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}


def full_inputs(root):
    refs = {rid: write_ref(root, rid) for rid in CATEGORY_BY_REQUIREMENT}
    records = [{"id": rid, "status": "PASS", "evidence": [refs[rid]]} for rid in CATEGORY_BY_REQUIREMENT]
    gates = {gate_id: {"status": "PASS", "evidence": [refs[rid] for rid in sorted(required_ids)]}
             for gate_id, required_ids in GATE_REQUIREMENTS.items()}
    return records, gates


def test_assessment_requires_exact_20_requirements_verified_evidence_and_six_gates(tmp_path):
    records, gates = full_inputs(tmp_path)
    scope = review_scope_sha256(CATEGORY_BY_REQUIREMENT, records, gates, 0)
    signoff_path = tmp_path / "review-signoff.json"
    signoff_path.write_text(json.dumps({"status": "VERIFIED", "reviewer_role": "INDEPENDENT",
                                        "reviewer_id": "reviewer-1", "decision": "APPROVED",
                                        "scope_sha256": scope}), encoding="utf-8")
    signoff = {"path": signoff_path.name, "sha256": sha256(signoff_path.read_bytes()).hexdigest()}
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, 0, evidence_root=tmp_path,
                        reviewer_signoff=signoff)
    assert result["requirement_count"] == 20
    assert result["total"] == 100
    assert result["complete"] is True


def test_reviewer_signoff_must_be_independent_and_bound_to_current_scope(tmp_path):
    records, gates = full_inputs(tmp_path)
    scope = review_scope_sha256(CATEGORY_BY_REQUIREMENT, records, gates, 0)
    path = tmp_path / "review-signoff.json"
    artifact = {"status": "VERIFIED", "reviewer_role": "INDEPENDENT", "reviewer_id": "reviewer-1",
                "decision": "APPROVED", "scope_sha256": scope}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    ref = {"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}
    artifact["scope_sha256"] = "0" * 64
    path.write_text(json.dumps(artifact), encoding="utf-8")
    ref["sha256"] = sha256(path.read_bytes()).hexdigest()
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, 0, evidence_root=tmp_path, reviewer_signoff=ref)
    assert result["reviewer_signoff"] == "SCOPE_MISMATCH"
    assert result["complete"] is False


def test_missing_evidence_gate_or_unknown_defect_audit_never_completes(tmp_path):
    records, gates = full_inputs(tmp_path)
    records[0]["evidence"] = ["checkbox-done"]
    gates["G5"] = {"status": "PASS", "evidence": []}
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, None, evidence_root=tmp_path)
    assert not result["complete"]
    assert result["defect_audit"] == "NOT_EVALUATED"


def test_partial_criterion_status_does_not_earn_validation_points(tmp_path):
    records, gates = full_inputs(tmp_path)
    path = tmp_path / "C2-R15.json"
    path.write_text(json.dumps({"requirement_id": "C2-R15", "status": "VERIFIED",
                                "criterion_status": "PARTIAL_NO_ADJUDICATED_DATASET"}), encoding="utf-8")
    records[14]["evidence"] = [{"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}]
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, 0, evidence_root=tmp_path)
    assert result["points"]["V"] < 20
    assert "C2-R15" not in result["verified_requirements"]


def test_unrecognized_criterion_status_does_not_earn_requirement_credit(tmp_path):
    records, gates = full_inputs(tmp_path)
    path = tmp_path / "C2-R15.json"
    path.write_text(json.dumps({"requirement_id": "C2-R15", "status": "VERIFIED",
                                "criterion_status": "BLOCKED_REVIEW_PENDING"}), encoding="utf-8")
    records[14]["evidence"] = [{"path": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}]
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, 0, evidence_root=tmp_path)
    assert "C2-R15" not in result["verified_requirements"]
    assert result["points"]["V"] < 20


def test_gate_evidence_must_bind_to_the_specific_gate(tmp_path):
    records, gates = full_inputs(tmp_path)
    gates["G4"]["evidence"] = gates["G3"]["evidence"]
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, 0, evidence_root=tmp_path)
    assert result["gates_pass"] is False
    assert result["complete"] is False


def test_requirement_set_category_mapping_and_duplicate_rejected(tmp_path):
    records, gates = full_inputs(tmp_path)
    with pytest.raises(ValueError, match="REQUIREMENT_SET_MISMATCH"):
        completion({"C2-R01": "D"}, [], {}, 0, evidence_root=tmp_path)
    with pytest.raises(ValueError, match="DUPLICATE_REQUIREMENT"):
        completion(CATEGORY_BY_REQUIREMENT, records + [records[0]], gates, 0, evidence_root=tmp_path)
    wrong = dict(CATEGORY_BY_REQUIREMENT)
    wrong["C2-R01"] = "C"
    with pytest.raises(ValueError, match="CATEGORY_MAP_MISMATCH"):
        completion(wrong, records, gates, 0, evidence_root=tmp_path)


def test_full_score_and_zero_defects_still_require_independent_reviewer_signoff(tmp_path):
    records, gates = full_inputs(tmp_path)
    result = completion(CATEGORY_BY_REQUIREMENT, records, gates, 0, evidence_root=tmp_path, reviewer_signoff=None)
    assert result["total"] == 100
    assert result["reviewer_signoff"] == "NOT_PERFORMED"
    assert result["complete"] is False
