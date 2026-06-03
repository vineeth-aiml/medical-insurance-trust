import json
import re
from pathlib import Path
from typing import Dict, List

import requests

from app.core.config import settings


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def load_known_doctors() -> List[Dict]:
    path = Path(settings.known_doctors_file)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _local_registry_match(doctor_names: List[str], reg_numbers: List[str]) -> List[Dict]:
    matches = []
    known = load_known_doctors()
    for doctor in known:
        known_name = _norm(doctor.get("name") or doctor.get("doctor_name") or "")
        known_reg = _norm(doctor.get("registration_number") or doctor.get("reg_no") or "")
        for name in doctor_names:
            name_norm = _norm(name.replace("Dr.", ""))
            if name_norm and (name_norm in known_name or known_name in name_norm):
                matches.append({**doctor, "match_type": "name"})
        for reg in reg_numbers:
            if known_reg and _norm(reg).replace(" ", "") == known_reg.replace(" ", ""):
                matches.append({**doctor, "match_type": "registration"})
    return matches


def _external_nmc_lookup(doctor_names: List[str], reg_numbers: List[str]) -> Dict:
    if not settings.nmc_api_base_url:
        return {"available": False, "matches": [], "reasons": ["NMC/state medical council API not configured"]}
    headers = {"Authorization": f"Bearer {settings.nmc_api_token}"} if settings.nmc_api_token else {}
    try:
        response = requests.post(
            f"{settings.nmc_api_base_url.rstrip('/')}/verify-doctor",
            json={"doctor_names": doctor_names, "registration_numbers": reg_numbers},
            headers=headers,
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        return {"available": True, "matches": data.get("matches", []), "reasons": data.get("reasons", [])}
    except Exception as exc:
        return {"available": True, "matches": [], "reasons": [f"Doctor registry lookup failed: {exc}"]}


def validate_doctor(extracted: Dict) -> Dict:
    doctor_names = extracted.get("doctor_names", []) or []
    registration_numbers = extracted.get("registration_numbers", []) or []
    reasons = []

    if not doctor_names:
        reasons.append("Doctor name not found in document")
    if not registration_numbers:
        reasons.append("Doctor registration number not found")

    local_matches = _local_registry_match(doctor_names, registration_numbers)
    external = _external_nmc_lookup(doctor_names, registration_numbers)
    external_matches = external.get("matches", []) or []

    if local_matches or external_matches:
        risk = 0.0
        reasons.append("Doctor matched a verified source")
    else:
        # Missing registration is common in small Indian clinics, so it is review risk, not automatic fraud.
        risk = 0.3 if doctor_names else 0.55
        if registration_numbers:
            risk = max(risk, 0.65)
            reasons.append("Registration number was present but did not match configured verified source")
        reasons.extend(external.get("reasons", []))

    # Specialty consistency hook for production.
    specialty_notes = []
    known_specialties = [m.get("specialty") for m in local_matches + external_matches if m.get("specialty")]
    if known_specialties and extracted.get("diagnosis_keywords"):
        specialty_notes.append(f"Known specialty: {', '.join(sorted(set(known_specialties)))}")

    return {
        "doctor_authenticity_risk": round(float(risk), 2),
        "doctor_names": doctor_names,
        "registration_numbers": registration_numbers,
        "registry_matches": local_matches + external_matches,
        "external_registry": external,
        "specialty_notes": specialty_notes,
        "reasons": reasons,
        "note": "Production should connect to NMC/state medical council or verified clinic master data. This service already supports a configurable provider endpoint.",
    }
