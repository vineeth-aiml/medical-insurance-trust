from typing import Dict

WEIGHTS = {
    "forensic": 0.25,
    "doctor": 0.15,
    "medical": 0.10,
    "behavior": 0.15,
    "quality": 0.10,
    "hospital": 0.15,
    "signature_stamp": 0.10,
}


def _quality_risk(quality_payload: Dict) -> float:
    qualities = quality_payload.get("quality", []) or []
    if not qualities:
        return 0.2
    min_score = min(float(q.get("quality_score", 100)) for q in qualities)
    if min_score < 40:
        return 0.6
    if min_score < 60:
        return 0.35
    if min_score < 75:
        return 0.2
    return 0.0


def _level(score: float) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def _decision(score: float) -> str:
    if score >= 70:
        return "HIGH_RISK_REVIEW"
    if score >= 30:
        return "MANUAL_REVIEW"
    return "LOW_RISK"


def final_score(quality_payload: Dict, forensic: Dict, doctor: Dict, medical: Dict, behavior: Dict, hospital: Dict | None = None, signature_stamp: Dict | None = None) -> Dict:
    hospital = hospital or {}
    signature_stamp = signature_stamp or {}
    component_risks = {
        "forensic": float(forensic.get("overall_forensic_risk", 0)),
        "doctor": float(doctor.get("doctor_authenticity_risk", 0)),
        "medical": float(medical.get("medical_plausibility_risk", 0)),
        "behavior": float(behavior.get("behavior_risk", 0)),
        "quality": _quality_risk(quality_payload),
        "hospital": float(hospital.get("hospital_verification_risk", 0)),
        "signature_stamp": float(signature_stamp.get("signature_stamp_risk", 0)),
    }
    score = sum(component_risks[k] * WEIGHTS[k] for k in WEIGHTS) * 100
    score = round(min(max(score, 0), 100), 2)
    top_reasons = []
    for payload in [forensic, doctor, medical, behavior, hospital, signature_stamp]:
        top_reasons.extend(payload.get("reasons", []) or [])
    if not top_reasons:
        top_reasons.append("No major fraud signal detected")
    return {
        "risk_score": score,
        "risk_level": _level(score),
        "decision": _decision(score),
        "component_risks": component_risks,
        "weights": WEIGHTS,
        "top_reasons": top_reasons[:8],
    }
