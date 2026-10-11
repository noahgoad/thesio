"""Evidence-backed v1 completion scoring for Narrative Research Desk."""

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

WEIGHTS = {"D": 15, "C": 25, "U": 15, "R": 15, "V": 20, "H": 10}
CATEGORY_BY_REQUIREMENT = {
    **{f"C2-R{i:02d}": "D" for i in range(1, 4)},
    **{f"C2-R{i:02d}": "C" for i in range(4, 9)},
    **{f"C2-R{i:02d}": "U" for i in range(9, 12)},
    **{f"C2-R{i:02d}": "R" for i in range(12, 15)},
    **{f"C2-R{i:02d}": "V" for i in range(15, 19)},
    **{f"C2-R{i:02d}": "H" for i in range(19, 21)},
}
GATE_IDS = {f"G{i}" for i in range(6)}
GATE_REQUIREMENTS = {
    "G0": {"C2-R01", "C2-R12"},
    "G1": {"C2-R02", "C2-R03"},
    "G2": {f"C2-R{i:02d}" for i in range(4, 9)},
    "G3": {f"C2-R{i:02d}" for i in range(9, 15)},
    "G4": {f"C2-R{i:02d}" for i in range(15, 19)},
    "G5": {"C2-R19", "C2-R20"},
}


def review_scope_sha256(expected: dict[str, str], records: list[dict], gates: dict[str, Any],
                        high_defects: int | None) -> str:
    """Return the deterministic digest an independent reviewer must attest to."""
    payload = {"expected": expected, "records": records, "gates": gates, "high_defects": high_defects}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _verified_refs(refs: Any, root: Path | None, requirement_id: str | None = None,
                   gate_id: str | None = None, required_ids: set[str] | None = None) -> bool:
    if not isinstance(refs, list) or not refs or root is None:
        return False
    root = root.resolve()
    seen_ids = set()
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            return False
        relative = Path(ref["path"])
        if relative.is_absolute():
            return False
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return False
        if sha256(path.read_bytes()).hexdigest() != ref.get("sha256"):
            return False
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(artifact, dict) or artifact.get("status") != "VERIFIED":
            return False
        if requirement_id:
            if artifact.get("requirement_id") != requirement_id:
                return False
            criterion_status = artifact.get("criterion_status")
            if criterion_status is not None and criterion_status != "PASS":
                return False
        if required_ids is not None:
            artifact_id = artifact.get("requirement_id")
            if artifact_id not in required_ids or artifact_id in seen_ids:
                return False
            criterion_status = artifact.get("criterion_status")
            if criterion_status is not None and criterion_status != "PASS":
                return False
            seen_ids.add(artifact_id)
        if gate_id and artifact.get("gate_id") != gate_id:
            return False
    return required_ids is None or seen_ids == required_ids


def completion(expected: dict[str, str], records: list[dict], gates: dict[str, Any], high_defects: int | None,
               evidence_root: Path | None = None, reviewer_signoff: dict | None = None) -> dict[str, Any]:
    if set(expected) != set(CATEGORY_BY_REQUIREMENT):
        raise ValueError("REQUIREMENT_SET_MISMATCH")
    ids = [row.get("id") for row in records]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_REQUIREMENT")
    if set(ids) != set(expected):
        raise ValueError("REQUIREMENT_SET_MISMATCH")
    if expected != CATEGORY_BY_REQUIREMENT:
        raise ValueError("CATEGORY_MAP_MISMATCH")
    if high_defects is not None and (not isinstance(high_defects, int) or isinstance(high_defects, bool) or high_defects < 0):
        raise ValueError("DEFECT_COUNT_INVALID")
    by_id = {row["id"]: row for row in records}
    points: dict[str, float] = {}
    verified: list[str] = []
    for category, weight in WEIGHTS.items():
        requirement_ids = [rid for rid, assigned in expected.items() if assigned == category]
        if not requirement_ids:
            raise ValueError("EMPTY_CATEGORY")
        passed = 0
        for rid in requirement_ids:
            row = by_id[rid]
            if row.get("status") == "PASS" and _verified_refs(row.get("evidence"), evidence_root, rid):
                passed += 1
                verified.append(rid)
        points[category] = weight * passed / len(requirement_ids)
    gate_pass = set(gates) == GATE_IDS and all(
        isinstance(gates[gate_id], dict)
        and gates[gate_id].get("status") == "PASS"
        and _verified_refs(gates[gate_id].get("evidence"), evidence_root, required_ids=GATE_REQUIREMENTS[gate_id])
        for gate_id in GATE_IDS
    )
    total = sum(points.values())
    scope_sha256 = review_scope_sha256(expected, records, gates, high_defects)
    reviewer_status = "NOT_PERFORMED"
    if reviewer_signoff is not None:
        if not _verified_refs([reviewer_signoff], evidence_root):
            reviewer_status = "INVALID"
        else:
            artifact = json.loads((evidence_root / reviewer_signoff["path"]).read_text(encoding="utf-8"))
            if artifact.get("reviewer_role") != "INDEPENDENT" or not isinstance(artifact.get("reviewer_id"), str) or not artifact["reviewer_id"].strip():
                reviewer_status = "INVALID"
            elif artifact.get("decision") != "APPROVED":
                reviewer_status = "REJECTED"
            elif artifact.get("scope_sha256") != scope_sha256:
                reviewer_status = "SCOPE_MISMATCH"
            else:
                reviewer_status = "APPROVED"
    return {"points": points, "total": total, "software_pct": (total - points["V"]) / 80 * 100,
            "validation_pct": points["V"] / 20 * 100, "requirement_count": len(expected),
            "verified_requirements": sorted(verified), "gates_pass": gate_pass,
            "defect_audit": "PASS" if high_defects == 0 else "OPEN" if high_defects is not None else "NOT_EVALUATED",
            "reviewer_signoff": reviewer_status, "review_scope_sha256": scope_sha256,
            "complete": total == 100 and gate_pass and high_defects == 0 and reviewer_status == "APPROVED"}
