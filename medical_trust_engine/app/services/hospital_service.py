import json
from pathlib import Path
from typing import Dict, List

import cv2
import requests

from app.core.config import settings


def decode_qr_codes(page_paths: List[Path]) -> List[Dict]:
    detector = cv2.QRCodeDetector()
    found = []
    for path in page_paths:
        img = cv2.imread(str(path))
        if img is None:
            continue
        try:
            ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
            if ok:
                for text in decoded_info:
                    if text:
                        found.append({"image": str(path), "qr_text": text})
            else:
                text, points, _ = detector.detectAndDecode(img)
                if text:
                    found.append({"image": str(path), "qr_text": text})
        except Exception:
            continue
    return found


def load_verified_invoices() -> list[dict]:
    path = settings.verified_invoices_file
    if not Path(path).exists():
        return []
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []


def verify_invoice_local(extracted: Dict) -> Dict:
    invoices = load_verified_invoices()
    candidates = set(extracted.get("invoice_numbers", []) or [])
    hospital = (extracted.get("hospital_name") or "").lower()
    amount = float(extracted.get("max_amount") or 0)
    dates = set(extracted.get("dates", []) or [])

    for record in invoices:
        rec_invoice = str(record.get("invoice_number", ""))
        if rec_invoice and rec_invoice in candidates:
            mismatches = []
            if record.get("amount") and amount and abs(float(record["amount"]) - amount) > 1:
                mismatches.append("Invoice amount does not match verified source")
            if record.get("date") and dates and str(record["date"]) not in dates:
                mismatches.append("Invoice date does not match verified source")
            if record.get("hospital_name") and hospital and str(record["hospital_name"]).lower() not in hospital:
                mismatches.append("Hospital name does not match verified source")
            return {
                "verified": not mismatches,
                "source": "local_verified_invoice_cache",
                "risk": 0.85 if mismatches else 0.0,
                "reasons": mismatches or ["Invoice matched verified source"],
                "matched_invoice": rec_invoice,
            }
    return {"verified": False, "source": "local_verified_invoice_cache", "risk": 0.2 if candidates else 0.0, "reasons": ["Invoice not found in verified invoice cache"] if candidates else ["No invoice number available"]}


def verify_invoice_external(extracted: Dict) -> Dict:
    if not settings.hospital_api_base_url:
        return {"available": False, "risk": 0.0, "reasons": ["Hospital API verification not configured"]}
    headers = {"Authorization": f"Bearer {settings.hospital_api_token}"} if settings.hospital_api_token else {}
    payload = {
        "invoice_numbers": extracted.get("invoice_numbers", []),
        "hospital_name": extracted.get("hospital_name"),
        "dates": extracted.get("dates", []),
        "amount": extracted.get("max_amount", 0),
        "uhid_numbers": extracted.get("uhid_numbers", []),
    }
    try:
        response = requests.post(f"{settings.hospital_api_base_url.rstrip('/')}/verify-invoice", json=payload, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()
        return {
            "available": True,
            "verified": bool(data.get("verified")),
            "risk": 0.0 if data.get("verified") else 0.9,
            "reasons": data.get("reasons") or (["Hospital source verified invoice"] if data.get("verified") else ["Hospital source did not verify invoice"]),
            "source": "external_hospital_api",
            "raw": data,
        }
    except Exception as exc:
        return {"available": True, "verified": False, "risk": 0.1, "reasons": [f"Hospital API verification failed: {exc}"], "source": "external_hospital_api"}


def verify_hospital_invoice(page_paths: List[Path], extracted: Dict) -> Dict:
    qr_codes = decode_qr_codes(page_paths)
    qr_risk = 0.0
    qr_reasons = []
    if qr_codes:
        qr_text_joined = "\n".join(q["qr_text"] for q in qr_codes).lower()
        for invoice in extracted.get("invoice_numbers", []) or []:
            if invoice.lower() not in qr_text_joined:
                qr_risk = max(qr_risk, 0.4)
                qr_reasons.append("QR code exists but extracted invoice number was not found inside QR payload")
        if extracted.get("max_amount") and str(int(extracted["max_amount"])) not in qr_text_joined:
            qr_risk = max(qr_risk, 0.35)
            qr_reasons.append("QR code exists but bill amount was not found inside QR payload")
        if not qr_reasons:
            qr_reasons.append("QR code decoded and no mismatch was found")
    else:
        qr_reasons.append("No QR code detected")

    local = verify_invoice_local(extracted)
    external = verify_invoice_external(extracted)
    risks = [qr_risk, local.get("risk", 0), external.get("risk", 0)]
    risk = max(risks)

    reasons = []
    reasons.extend(qr_reasons)
    reasons.extend(local.get("reasons", []))
    reasons.extend(external.get("reasons", []))

    return {
        "hospital_verification_risk": round(float(risk), 2),
        "qr_codes": qr_codes,
        "local_invoice_check": local,
        "external_invoice_check": external,
        "reasons": reasons,
    }
