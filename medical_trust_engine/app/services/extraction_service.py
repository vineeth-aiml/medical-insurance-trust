import re
from typing import Dict, List

DATE_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b\d{1,2}\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s*\d{2,4}\b",
]
AMOUNT_PATTERNS = [
    r"(?:₹|Rs\.?|INR)\s*[,\d]+(?:\.\d{1,2})?",
    r"\b(?:total amount|grand total|net amount|paid amount|amount|rate)\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*[,\d]+(?:\.\d{1,2})?",
]
REG_PATTERNS = [
    r"\b(?:Reg\.?\s*No\.?|Registration\s*No\.?|MCI\s*No\.?|NMC\s*No\.?)\s*[:\-]?\s*([A-Z]{0,8}\s*[-/]?\s*\d{3,8})\b",
    r"\b(?:TSMC|KMC|APMC|MMC|DMC|MCI|NMC|TNMC|MPC|GMC)\s*[-/]?\s*\d{3,8}\b",
]
DOCTOR_PATTERN = r"\b(?:Dr|Doctor|Consultant|Prescribing Doctor|Conducting Doctor)\.?\s*[:\-]?\s*([A-Z][A-Za-z.\s]{2,55})"
LEAVE_PATTERN = r"\b(?:rest|leave|bed rest|medical leave)\s*(?:for)?\s*(\d{1,3})\s*(?:days?|d)\b"
INVOICE_PATTERNS = [
    r"\b(?:invoice|inv|bill|receipt|order)\s*(?:no|number|#)?\s*[:\-/]?\s*([A-Z0-9][A-Z0-9\-/]{4,30})\b",
    r"\b(INV\d{4,}[A-Z0-9\-/]*)\b",
]
UHID_PATTERNS = [r"\b(?:UHID|MRN|OP\s*ID|IP\s*ID)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{3,30})\b"]

COMMON_DIAGNOSIS = [
    "fever", "viral fever", "cold", "cough", "flu", "dengue", "typhoid", "malaria",
    "fracture", "injury", "infection", "gastritis", "migraine", "back pain", "surgery",
    "stroke", "diabetes", "hypertension", "covid", "asthma", "neurology", "cardiology",
]
MEDICINE_HINTS = ["tablet", "tab", "capsule", "cap", "syrup", "injection", "inj", "mg", "ml", "ointment"]


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip(" :-,\t\n")


def _find_all(patterns: List[str], text: str, flags=re.IGNORECASE) -> List[str]:
    found: List[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags):
            if isinstance(match, tuple):
                match = next((m for m in match if m), "")
            value = _clean(match)
            if value and value not in found:
                found.append(value)
    return found


def extract_amounts(text: str) -> tuple[list[str], list[float]]:
    amount_texts = _find_all(AMOUNT_PATTERNS, text)
    values = []
    for item in amount_texts:
        numbers = re.findall(r"[\d,]+(?:\.\d{1,2})?", item)
        if numbers:
            try:
                values.append(float(numbers[-1].replace(",", "")))
            except Exception:
                pass
    # Also catch tabular total lines without amount prefix.
    for line in text.splitlines():
        if any(word in line.lower() for word in ["total", "paid", "net"]):
            nums = re.findall(r"\b\d{2,7}(?:\.\d{1,2})?\b", line.replace(",", ""))
            for n in nums:
                val = float(n)
                if val not in values:
                    values.append(val)
                    amount_texts.append(_clean(line))
    return amount_texts[:20], values[:20]


def detect_document_type(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["invoice", "paid amount", "total amount", "receipt", "bill"]):
        return "BILL"
    if any(word in lowered for word in ["prescription", "rx", "tablet", "capsule", "syrup"]):
        return "PRESCRIPTION"
    if any(word in lowered for word in ["lab", "report", "test", "radiology", "mri", "blood", "urine"]):
        return "LAB_REPORT"
    if any(word in lowered for word in ["leave", "bed rest", "medical certificate", "fitness certificate"]):
        return "MEDICAL_CERTIFICATE"
    return "UNKNOWN"


def extract_hospital_name(text: str) -> str:
    lines = [_clean(line) for line in text.splitlines() if _clean(line)]
    for line in lines[:10]:
        if any(token in line.lower() for token in ["hospital", "clinic", "diagnostic", "labs", "medical centre", "healthcare"]):
            return line[:120]
    return lines[0][:120] if lines else ""


def extract_fields(text: str) -> Dict:
    dates = _find_all(DATE_PATTERNS, text)
    amount_texts, amounts = extract_amounts(text)
    registration_numbers = _find_all(REG_PATTERNS, text)
    invoice_numbers = _find_all(INVOICE_PATTERNS, text)
    uhid_numbers = _find_all(UHID_PATTERNS, text)

    doctor_names: List[str] = []
    for match in re.findall(DOCTOR_PATTERN, text, flags=re.IGNORECASE):
        name = _clean("Dr. " + match)
        name = re.sub(r"\b(OP ID|Prescribing Doctor|Conducting Doctor|Consultant)\b.*", "", name, flags=re.IGNORECASE).strip()
        if 4 <= len(name) <= 80 and name not in doctor_names:
            doctor_names.append(name)

    diagnosis_keywords = [d for d in COMMON_DIAGNOSIS if re.search(rf"\b{re.escape(d)}\b", text, re.IGNORECASE)]
    leave_days = [int(x) for x in re.findall(LEAVE_PATTERN, text, re.IGNORECASE)]
    medicine_lines = []
    for line in text.splitlines():
        if any(hint in line.lower() for hint in MEDICINE_HINTS):
            medicine_lines.append(_clean(line))

    field_confidence = 0.0
    field_confidence += 0.2 if dates else 0
    field_confidence += 0.2 if amounts else 0
    field_confidence += 0.2 if doctor_names else 0
    field_confidence += 0.15 if invoice_numbers else 0
    field_confidence += 0.15 if registration_numbers else 0
    field_confidence += 0.1 if len(text) > 200 else 0

    return {
        "hospital_name": extract_hospital_name(text),
        "document_type": detect_document_type(text),
        "doctor_names": doctor_names[:10],
        "registration_numbers": registration_numbers[:10],
        "dates": dates[:20],
        "invoice_numbers": invoice_numbers[:10],
        "uhid_numbers": uhid_numbers[:10],
        "amount_texts": amount_texts,
        "amounts": amounts,
        "max_amount": max(amounts) if amounts else 0,
        "diagnosis_keywords": diagnosis_keywords,
        "possible_medicines": medicine_lines[:30],
        "leave_days": leave_days,
        "field_confidence": round(min(field_confidence, 1.0), 2),
    }
