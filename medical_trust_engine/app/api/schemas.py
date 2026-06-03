from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ClaimOut(BaseModel):
    claim_id: str
    employee_id: str
    file_name: str
    document_type: str
    status: str
    risk_score: float
    risk_level: str
    decision: str
    owner_message: Optional[str] = ""
    created_at: datetime

    class Config:
        from_attributes = True


class FraudSignalOut(BaseModel):
    signal_name: str
    confidence: float
    severity: str
    description: str
    evidence_path: Optional[str] = None


class ClaimDetailOut(BaseModel):
    claim_id: str
    employee_id: str
    file_name: str
    status: str
    document_type: str
    risk_score: float
    risk_level: str
    decision: str
    owner_message: str = ""
    raw_text: str
    extracted: Dict[str, Any]
    quality: Dict[str, Any]
    forensic: Dict[str, Any]
    doctor: Dict[str, Any]
    medical: Dict[str, Any]
    behavior: Dict[str, Any]
    hospital: Dict[str, Any]
    signature_stamp: Dict[str, Any]
    final: Dict[str, Any]
    signals: List[FraudSignalOut]
