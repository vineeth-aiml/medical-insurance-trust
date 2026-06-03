from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.db.database import Base


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(String(64), unique=True, index=True, nullable=False)
    employee_id = Column(String(128), index=True, nullable=False)
    file_name = Column(String(255), nullable=False)
    file_hash = Column(String(128), index=True, nullable=False)
    file_path = Column(Text, nullable=False)
    storage_backend = Column(String(32), default="local")
    storage_key = Column(Text, nullable=True)
    document_type = Column(String(64), default="UNKNOWN")
    status = Column(String(64), default="PROCESSING")
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String(64), default="UNKNOWN")
    decision = Column(String(64), default="PENDING")
    owner_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analysis = relationship("ClaimAnalysis", back_populates="claim", uselist=False, cascade="all, delete-orphan")
    signals = relationship("FraudSignal", back_populates="claim", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="claim", cascade="all, delete-orphan")


class ClaimAnalysis(Base):
    __tablename__ = "claim_analyses"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(String(64), ForeignKey("claims.claim_id"), unique=True, nullable=False)
    raw_text = Column(Text, default="")
    extracted_json = Column(Text, default="{}")
    quality_json = Column(Text, default="{}")
    forensic_json = Column(Text, default="{}")
    doctor_json = Column(Text, default="{}")
    medical_json = Column(Text, default="{}")
    behavior_json = Column(Text, default="{}")
    hospital_json = Column(Text, default="{}")
    signature_json = Column(Text, default="{}")
    final_json = Column(Text, default="{}")
    owner_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", back_populates="analysis")


class FraudSignal(Base):
    __tablename__ = "fraud_signals"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(String(64), ForeignKey("claims.claim_id"), index=True, nullable=False)
    signal_name = Column(String(128), nullable=False)
    confidence = Column(Float, default=0.0)
    severity = Column(String(32), default="LOW")
    description = Column(Text, nullable=False)
    evidence_path = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", back_populates="signals")


class DoctorProfile(Base):
    __tablename__ = "doctor_profiles"
    __table_args__ = (UniqueConstraint("registration_number", "doctor_name", name="uq_doctor_reg_name"),)

    id = Column(Integer, primary_key=True)
    doctor_name = Column(String(255), index=True, nullable=False)
    registration_number = Column(String(128), index=True, nullable=True)
    state_council = Column(String(128), nullable=True)
    specialty = Column(String(128), nullable=True)
    clinic_name = Column(String(255), nullable=True)
    verified = Column(Boolean, default=False)
    verification_source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ReferenceVisualProfile(Base):
    __tablename__ = "reference_visual_profiles"

    id = Column(Integer, primary_key=True)
    profile_type = Column(String(32), index=True, nullable=False)  # signature or stamp
    label = Column(String(255), nullable=False)
    doctor_name = Column(String(255), nullable=True)
    clinic_name = Column(String(255), nullable=True)
    image_path = Column(Text, nullable=False)
    phash = Column(String(128), nullable=True)
    dhash = Column(String(128), nullable=True)
    verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    claim_id = Column(String(64), ForeignKey("claims.claim_id"), index=True, nullable=True)
    actor = Column(String(128), default="system")
    action = Column(String(128), nullable=False)
    details = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", back_populates="audit_logs")
