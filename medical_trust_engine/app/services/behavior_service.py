from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy.orm import Session

from app.db.models import Claim, ClaimAnalysis


def analyze_employee_behavior(db: Session, employee_id: str, file_hash: str, extracted: Dict, current_claim_id: str = None) -> Dict:
    now = datetime.utcnow()
    last_90 = now - timedelta(days=90)

    recent_query = db.query(Claim).filter(Claim.employee_id == employee_id, Claim.created_at >= last_90)
    duplicate_query = db.query(Claim).filter(Claim.employee_id == employee_id, Claim.file_hash == file_hash)
    if current_claim_id:
        recent_query = recent_query.filter(Claim.claim_id != current_claim_id)
        duplicate_query = duplicate_query.filter(Claim.claim_id != current_claim_id)
    recent_claims = recent_query.all()
    duplicate_claims = duplicate_query.all()

    risk = 0.0
    reasons = []

    if len(recent_claims) >= 5:
        risk += 0.30
        reasons.append(f"Employee has {len(recent_claims)} claims in last 90 days")
    if len(duplicate_claims) >= 1:
        risk += 0.50
        reasons.append("Same file hash already submitted by this employee")

    doctor_names = set([d.lower() for d in extracted.get("doctor_names", [])])
    same_doctor_count = 0
    if doctor_names:
        for claim in recent_claims:
            if claim.analysis and claim.analysis.extracted_json:
                try:
                    import json
                    old = json.loads(claim.analysis.extracted_json)
                    old_doctors = set([d.lower() for d in old.get("doctor_names", [])])
                    if doctor_names & old_doctors:
                        same_doctor_count += 1
                except Exception:
                    pass
    if same_doctor_count >= 3:
        risk += 0.20
        reasons.append(f"Same doctor appears in {same_doctor_count} recent claims")

    if not reasons:
        reasons.append("No major employee behavior anomaly found")

    return {
        "recent_claim_count_90_days": len(recent_claims),
        "duplicate_file_count": len(duplicate_claims),
        "same_doctor_recent_count": same_doctor_count,
        "behavior_risk": round(min(risk, 1.0), 2),
        "reasons": reasons,
    }
