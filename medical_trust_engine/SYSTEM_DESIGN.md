# Production System Design — Medical Document Trust Engine

## HLD

```text
React/Jinja UI + REST API
        ↓
FastAPI Gateway
        ↓
Claim Service
        ↓
PostgreSQL claim record + MinIO original file storage
        ↓
Redis/Celery async worker
        ↓
Document Pipeline
        ├─ PDF/Image validation + page rendering
        ├─ OCR: PaddleOCR/Tesseract/native PDF text
        ├─ Field extraction: hospital, invoice, doctor, date, amount
        ├─ Image forensics: metadata, ELA, pHash/dHash, region rules
        ├─ Hospital verification: QR + invoice cache/API
        ├─ Doctor verification: local cache + NMC/state provider hook
        ├─ Signature/stamp matching: reference image profiles
        ├─ Medical plausibility rules
        └─ Employee behavior analytics
        ↓
Fraud Scoring Engine
        ↓
Owner-friendly final message + admin audit trail
```

## LLD Modules

### Upload and Storage

- Validates extension, size, MIME type.
- Stores original locally for processing.
- Uploads original to MinIO when enabled.
- Creates SHA256 hash for duplicate detection.

### OCR Service

- Uses native PDF text when present.
- Uses PaddleOCR when installed and configured.
- Uses Tesseract as fallback.
- Produces raw text, OCR boxes, image quality scores, selected OCR engine.

### Extraction Service

Extracts:

- Hospital/clinic name
- Doctor names
- Registration numbers
- Invoice numbers
- UHID/OP/IP IDs
- Dates
- Amounts
- Medicines
- Diagnosis keywords
- Leave days

### Forensic Service

Checks:

- Suspicious PDF metadata
- Modified timestamp mismatch
- ELA compression inconsistency
- Perceptual hashes
- Amount/date region risk rules

### Hospital Service

Checks:

- QR code content
- Local verified invoice cache
- External hospital verification provider when configured

### Doctor Service

Checks:

- Local verified doctor cache
- External NMC/state medical council provider when configured
- Registration number presence and match status

### Signature/Stamp Service

- Crops likely header/footer/signature/stamp regions.
- Compares candidates with verified reference images.
- Gives risk when references are missing or mismatch.

### Scoring Engine

Weights:

```text
forensic          25%
doctor            15%
medical           10%
behavior          15%
quality           10%
hospital          15%
signature/stamp   10%
```

Output:

```json
{
  "risk_score": 0-100,
  "risk_level": "LOW|MEDIUM|HIGH",
  "decision": "LOW_RISK|MANUAL_REVIEW|HIGH_RISK_REVIEW",
  "owner_message": "client-friendly text"
}
```

## Production Notes

- High/medium risk should trigger manual review, not automatic rejection.
- No single module decides fraud.
- Add real provider data for doctor/hospital verification to increase accuracy.
- Add Alembic migrations before long-term production maintenance.
