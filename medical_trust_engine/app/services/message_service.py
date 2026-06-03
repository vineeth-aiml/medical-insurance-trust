from typing import Dict


def build_owner_message(claim_id: str, extracted: Dict, final: Dict, doctor: Dict, hospital: Dict, signature_stamp: Dict) -> str:
    risk_level = final.get("risk_level", "UNKNOWN")
    decision = final.get("decision", "PENDING")
    score = final.get("risk_score", 0)
    hospital_name = extracted.get("hospital_name") or "Not clearly detected"
    date = ", ".join(extracted.get("dates", [])[:2]) or "Not clearly detected"
    doctor = ", ".join(extracted.get("doctor_names", [])[:2]) or "Not clearly detected"
    amount = extracted.get("max_amount") or 0
    doc_type = extracted.get("document_type", "UNKNOWN")

    if risk_level == "HIGH":
        status = "High risk. Do not approve automatically; send this claim for manual fraud review."
    elif risk_level == "MEDIUM":
        status = "Medium risk. Manual verification is recommended before approval."
    else:
        status = "Low risk. No major fraud signs were detected by the current checks."

    reasons = final.get("top_reasons", []) or []
    clean_reasons = []
    for reason in reasons:
        if reason and reason not in clean_reasons:
            clean_reasons.append(reason)
    if not clean_reasons:
        clean_reasons = ["No major fraud signal detected"]

    lines = [
        f"Claim {claim_id} has been analysed.",
        "",
        f"Result: {risk_level} RISK",
        f"Decision: {decision}",
        f"Risk Score: {score}/100",
        "",
        status,
        "",
        "Extracted Details:",
        f"Hospital/Clinic: {hospital_name}",
        f"Document Type: {doc_type}",
        f"Date: {date}",
        f"Doctor: {doctor}",
        f"Amount: ₹{float(amount):,.0f}" if amount else "Amount: Not clearly detected",
        "",
        "Main Review Notes:",
    ]
    lines.extend([f"- {r}" for r in clean_reasons[:5]])
    lines.extend([
        "",
        "Recommended Action:",
        "Approve only if this matches company policy and any required manual verification is complete." if risk_level == "LOW" else "Keep this claim in manual review until the highlighted issues are verified.",
    ])
    return "\n".join(lines)
