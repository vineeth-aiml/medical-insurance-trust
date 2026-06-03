import json
from pathlib import Path
from typing import Dict

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.scoring import final_score
from app.db.models import Claim, ClaimAnalysis, FraudSignal
from app.services.audit_service import audit
from app.services.behavior_service import analyze_employee_behavior
from app.services.doctor_service import validate_doctor
from app.services.extraction_service import extract_fields
from app.services.forensic_service import analyze_forensics
from app.services.hospital_service import verify_hospital_invoice
from app.services.medical_service import validate_medical_plausibility
from app.services.message_service import build_owner_message
from app.services.ocr_service import ocr_pages
from app.services.pdf_service import prepare_document_pages, save_json
from app.services.signature_stamp_service import analyze_signature_and_stamp


def _severity(confidence: float) -> str:
    if confidence >= 0.70:
        return "HIGH"
    if confidence >= 0.40:
        return "MEDIUM"
    return "LOW"


def _add_signal(db: Session, claim_id: str, name: str, confidence: float, description: str, evidence_path: str = None):
    db.add(FraudSignal(claim_id=claim_id, signal_name=name, confidence=round(float(confidence), 2), severity=_severity(confidence), description=description, evidence_path=evidence_path))


def build_signals(db: Session, claim_id: str, forensic: Dict, doctor: Dict, medical: Dict, behavior: Dict, quality_payload: Dict, hospital: Dict, signature_stamp: Dict):
    for payload, key, signal in [
        (forensic, "overall_forensic_risk", "forensic_signal"),
        (doctor, "doctor_authenticity_risk", "doctor_authenticity"),
        (medical, "medical_plausibility_risk", "medical_plausibility"),
        (behavior, "behavior_risk", "employee_behavior"),
        (hospital, "hospital_verification_risk", "hospital_invoice_qr_verification"),
        (signature_stamp, "signature_stamp_risk", "signature_stamp_matching"),
    ]:
        risk = float(payload.get(key, 0) or 0)
        if risk > 0:
            for reason in payload.get("reasons", []) or []:
                _add_signal(db, claim_id, signal, risk, reason)

    for ela in forensic.get("ela_analysis", []) or []:
        if ela.get("risk", 0) > 0:
            _add_signal(db, claim_id, "ela_compression_inconsistency", ela.get("risk", 0), "ELA compression inconsistency found; edited/resaved region may exist", ela.get("ela_output"))

    for q in quality_payload.get("quality", []) or []:
        if q.get("quality_score", 100) < 60:
            _add_signal(db, claim_id, "poor_scan_quality", 0.45, f"Low quality scan may reduce OCR reliability: quality={q.get('quality_score')}", q.get("image"))


def _claim_dir(claim: Claim) -> Path:
    return settings.processed_dir / claim.claim_id


def run_claim_pipeline(db: Session, claim: Claim) -> Claim:
    try:
        claim_dir = _claim_dir(claim)
        claim_dir.mkdir(parents=True, exist_ok=True)
        audit(db, "pipeline_started", claim_id=claim.claim_id, file_name=claim.file_name)

        page_paths, pdf_info, native_text = prepare_document_pages(Path(claim.file_path), claim_dir)
        save_json(claim_dir / "pdf_info.json", pdf_info)

        ocr_result = ocr_pages(page_paths, native_text, claim_dir)
        save_json(claim_dir / "ocr" / "ocr_result.json", ocr_result)

        raw_text = ocr_result.get("raw_text", "")
        extracted = extract_fields(raw_text)
        save_json(claim_dir / "extracted_fields.json", extracted)

        forensic = analyze_forensics(page_paths, pdf_info, extracted, raw_text, claim_dir)
        save_json(claim_dir / "forensic" / "forensic_result.json", forensic)

        doctor = validate_doctor(extracted)
        save_json(claim_dir / "doctor_validation.json", doctor)

        hospital = verify_hospital_invoice(page_paths, extracted)
        save_json(claim_dir / "hospital_verification.json", hospital)

        signature_stamp = analyze_signature_and_stamp(page_paths, claim_dir)
        save_json(claim_dir / "signature_stamp.json", signature_stamp)

        medical = validate_medical_plausibility(extracted)
        save_json(claim_dir / "medical_validation.json", medical)

        behavior = analyze_employee_behavior(db, claim.employee_id, claim.file_hash, extracted, claim.claim_id)
        save_json(claim_dir / "behavior.json", behavior)

        quality_payload = {"quality": ocr_result.get("quality", [])}
        final = final_score(quality_payload, forensic, doctor, medical, behavior, hospital, signature_stamp)
        owner_message = build_owner_message(claim.claim_id, extracted, final, doctor, hospital, signature_stamp)
        final["owner_message"] = owner_message
        save_json(claim_dir / "final_report.json", final)

        claim.document_type = extracted.get("document_type", "UNKNOWN")
        claim.risk_score = final["risk_score"]
        claim.risk_level = final["risk_level"]
        claim.decision = final["decision"]
        claim.owner_message = owner_message
        claim.status = "COMPLETED"

        if claim.analysis:
            analysis = claim.analysis
            analysis.raw_text = raw_text
            analysis.extracted_json = json.dumps(extracted, ensure_ascii=False)
            analysis.quality_json = json.dumps(quality_payload, ensure_ascii=False)
            analysis.forensic_json = json.dumps(forensic, ensure_ascii=False)
            analysis.doctor_json = json.dumps(doctor, ensure_ascii=False)
            analysis.medical_json = json.dumps(medical, ensure_ascii=False)
            analysis.behavior_json = json.dumps(behavior, ensure_ascii=False)
            analysis.hospital_json = json.dumps(hospital, ensure_ascii=False)
            analysis.signature_json = json.dumps(signature_stamp, ensure_ascii=False)
            analysis.final_json = json.dumps(final, ensure_ascii=False)
            analysis.owner_message = owner_message
        else:
            db.add(ClaimAnalysis(
                claim_id=claim.claim_id,
                raw_text=raw_text,
                extracted_json=json.dumps(extracted, ensure_ascii=False),
                quality_json=json.dumps(quality_payload, ensure_ascii=False),
                forensic_json=json.dumps(forensic, ensure_ascii=False),
                doctor_json=json.dumps(doctor, ensure_ascii=False),
                medical_json=json.dumps(medical, ensure_ascii=False),
                behavior_json=json.dumps(behavior, ensure_ascii=False),
                hospital_json=json.dumps(hospital, ensure_ascii=False),
                signature_json=json.dumps(signature_stamp, ensure_ascii=False),
                final_json=json.dumps(final, ensure_ascii=False),
                owner_message=owner_message,
            ))

        build_signals(db, claim.claim_id, forensic, doctor, medical, behavior, quality_payload, hospital, signature_stamp)
        audit(db, "pipeline_completed", claim_id=claim.claim_id, risk_score=claim.risk_score, risk_level=claim.risk_level)
        db.commit()
        db.refresh(claim)
        return claim

    except Exception as exc:
        error_payload = {"risk_score": 0.0, "risk_level": "UNKNOWN", "decision": "PROCESSING_FAILED", "error": str(exc)}
        owner_message = f"Claim {claim.claim_id} processing failed. Reason: {exc}. Please re-upload the document or send it for manual review."
        claim.status = "FAILED"
        claim.decision = "PROCESSING_FAILED"
        claim.risk_score = 0.0
        claim.risk_level = "UNKNOWN"
        claim.owner_message = owner_message

        if claim.analysis:
            claim.analysis.final_json = json.dumps(error_payload, ensure_ascii=False)
            claim.analysis.owner_message = owner_message
        else:
            db.add(ClaimAnalysis(claim_id=claim.claim_id, raw_text="", extracted_json="{}", quality_json="{}", forensic_json="{}", doctor_json="{}", medical_json="{}", behavior_json="{}", hospital_json="{}", signature_json="{}", final_json=json.dumps(error_payload, ensure_ascii=False), owner_message=owner_message))

        db.add(FraudSignal(claim_id=claim.claim_id, signal_name="processing_error", confidence=1.0, severity="HIGH", description=str(exc)))
        audit(db, "pipeline_failed", claim_id=claim.claim_id, error=str(exc))
        db.commit()
        db.refresh(claim)
        return claim


def analysis_to_dict(claim: Claim) -> Dict:
    def parse(value):
        try:
            return json.loads(value or "{}")
        except Exception:
            return {}

    analysis = claim.analysis
    return {
        "claim_id": claim.claim_id,
        "employee_id": claim.employee_id,
        "file_name": claim.file_name,
        "status": claim.status,
        "document_type": claim.document_type,
        "risk_score": claim.risk_score,
        "risk_level": claim.risk_level,
        "decision": claim.decision,
        "owner_message": claim.owner_message or (analysis.owner_message if analysis else ""),
        "raw_text": analysis.raw_text if analysis else "",
        "extracted": parse(analysis.extracted_json) if analysis else {},
        "quality": parse(analysis.quality_json) if analysis else {},
        "forensic": parse(analysis.forensic_json) if analysis else {},
        "doctor": parse(analysis.doctor_json) if analysis else {},
        "medical": parse(analysis.medical_json) if analysis else {},
        "behavior": parse(analysis.behavior_json) if analysis else {},
        "hospital": parse(analysis.hospital_json) if analysis else {},
        "signature_stamp": parse(analysis.signature_json) if analysis else {},
        "final": parse(analysis.final_json) if analysis else {},
        "signals": [{"signal_name": s.signal_name, "confidence": s.confidence, "severity": s.severity, "description": s.description, "evidence_path": s.evidence_path} for s in claim.signals],
    }
