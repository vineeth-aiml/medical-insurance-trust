from typing import Dict, List


HIGH_AMOUNT_THRESHOLDS = {
    "PRESCRIPTION": 8000,
    "BILL": 50000,
    "LAB_REPORT": 30000,
    "MEDICAL_CERTIFICATE": 0,
    "UNKNOWN": 40000,
}

DIAGNOSIS_MEDICINE_RULES = {
    "fever": ["paracetamol", "dolo", "crocin", "azith", "antibiotic", "ors"],
    "cold": ["cetirizine", "paracetamol", "syrup", "steam", "azith"],
    "cough": ["syrup", "cetirizine", "levocet", "azith"],
    "diabetes": ["metformin", "insulin", "glimepiride"],
    "hypertension": ["amlodipine", "telmisartan", "atenolol", "losartan"],
}


def validate_medical_plausibility(extracted: Dict) -> Dict:
    reasons: List[str] = []
    risk = 0.0
    doc_type = extracted.get("document_type", "UNKNOWN")
    amount = float(extracted.get("max_amount") or 0)
    diagnosis = [d.lower() for d in extracted.get("diagnosis_keywords", []) or []]
    meds = "\n".join(extracted.get("possible_medicines", []) or []).lower()
    leave_days = extracted.get("leave_days", []) or []

    threshold = HIGH_AMOUNT_THRESHOLDS.get(doc_type, 40000)
    if threshold and amount > threshold:
        risk = max(risk, 0.45)
        reasons.append(f"Amount ₹{amount:,.0f} is high for document type {doc_type}; manual verification recommended")

    for days in leave_days:
        if days > 15 and any(d in diagnosis for d in ["cold", "cough", "fever", "viral fever"]):
            risk = max(risk, 0.75)
            reasons.append(f"Leave duration {days} days appears unusually high for minor illness keywords")
        elif days > 30:
            risk = max(risk, 0.5)
            reasons.append(f"Leave duration {days} days needs manual medical review")

    if diagnosis and extracted.get("possible_medicines"):
        for diag in diagnosis:
            expected = DIAGNOSIS_MEDICINE_RULES.get(diag)
            if expected and not any(x in meds for x in expected):
                risk = max(risk, 0.35)
                reasons.append(f"Medicines do not clearly match common treatment pattern for {diag}")

    if doc_type == "MEDICAL_CERTIFICATE" and not leave_days:
        risk = max(risk, 0.25)
        reasons.append("Medical certificate detected but leave/rest duration was not extracted")

    if not reasons:
        reasons.append("No major medical plausibility issue found by rule engine")

    return {
        "medical_plausibility_risk": round(float(risk), 2),
        "diagnosis_keywords": diagnosis,
        "medicine_line_count": len(extracted.get("possible_medicines", []) or []),
        "leave_days": leave_days,
        "reasons": reasons,
        "note": "For full production, add clinician-approved rules and/or an LLM audit layer. LLM output must be treated as review evidence, not final medical truth.",
    }
