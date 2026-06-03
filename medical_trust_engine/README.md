# Medical Document Trust Engine — Production Structured Version

This is the upgraded production-style codebase, not the earlier MVP. It keeps the app runnable on a laptop, but the architecture now includes the production components requested:

- PostgreSQL-ready database
- Redis + Celery background workers
- MinIO object storage
- PaddleOCR-ready OCR service with Tesseract fallback
- QR/invoice verification service
- Doctor registry verification provider hook for NMC/state council or internal verified source
- Signature/stamp matching service using reference-image matching
- Image forensics and ELA checks
- Owner-friendly final message instead of JSON-heavy client output
- Admin debug JSON hidden by default

> Important: No fraud system can honestly guarantee 100% detection. This version is production-structured and extensible, but real production accuracy depends on verified doctor data, hospital integrations, signature/stamp reference samples, OCR model quality, and human review policy.

---

## 1. Run locally in Windows CMD, simple mode

This uses SQLite/local files and runs synchronously. Good for quick testing.

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

If you used an older MVP database, delete it before running this upgraded version:

```cmd
del medical_trust_engine.db
rmdir /s /q data
```

---

## 2. Run production stack with Docker

This starts:

- FastAPI web app
- Celery worker
- PostgreSQL
- Redis
- MinIO

```cmd
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000
```

MinIO console:

```text
http://127.0.0.1:9001
```

Default MinIO login:

```text
minioadmin / minioadmin
```

---

## 3. How the production workflow works

```text
Upload PDF/Image
    ↓
Store original file locally + MinIO
    ↓
Create claim in PostgreSQL
    ↓
Queue claim to Celery worker
    ↓
Render PDF pages / normalize images
    ↓
OCR using PaddleOCR if installed, otherwise Tesseract/native PDF text
    ↓
Extract fields: hospital, doctor, date, invoice, UHID, amount, medicines, diagnosis
    ↓
Image forensic checks: metadata, ELA, perceptual hash, region rules
    ↓
QR + invoice verification
    ↓
Doctor registry/local verified doctor check
    ↓
Signature/stamp reference matching
    ↓
Medical plausibility rules
    ↓
Employee behavior analysis
    ↓
Weighted fraud score
    ↓
Owner-friendly message + dashboard
```

---

## 4. Owner-friendly output

The client/owner will not see raw JSON by default. They see a message like:

```text
Claim CLMxxxx has been analysed.

Result: LOW RISK
Decision: LOW_RISK
Risk Score: 12.5/100

Low risk. No major fraud signs were detected by the current checks.

Extracted Details:
Hospital/Clinic: Sidarth Hospitals
Document Type: BILL
Date: 22/01/2024
Doctor: Dr. Sidarth Reddy T
Amount: ₹12,500

Main Review Notes:
- QR code decoded and no mismatch was found
- Doctor registration number not found
- No major medical plausibility issue found by rule engine

Recommended Action:
Approve only if this matches company policy and any required manual verification is complete.
```

Raw JSON is hidden unless you set:

```env
SHOW_DEBUG_JSON=true
```

---

## 5. PaddleOCR / TrOCR upgrade

The service is already PaddleOCR-ready. To use it, install optional AI dependencies:

```cmd
pip install -r requirements-ai.txt
```

Then set:

```env
OCR_ENGINE=paddle
```

For GPU:

```env
PADDLE_USE_GPU=true
```

TrOCR is included as a production extension point. For real handwritten prescriptions, crop handwritten regions first, then pass those crops to a TrOCR adapter.

---

## 6. Doctor registry verification

The code supports three levels:

1. Local verified doctor cache: `app/seed_data/known_doctors.json`
2. Internal doctor master database
3. External provider endpoint:

```env
NMC_API_BASE_URL=https://your-doctor-registry-gateway.example.com
NMC_API_TOKEN=replace-me
```

Expected provider contract:

```http
POST /verify-doctor
```

Payload:

```json
{
  "doctor_names": ["Dr. Example"],
  "registration_numbers": ["TSMC12345"]
}
```

Response:

```json
{
  "matches": [
    {
      "name": "Dr. Example",
      "registration_number": "TSMC12345",
      "specialty": "Neurology",
      "verified": true
    }
  ],
  "reasons": ["Doctor matched registry"]
}
```

---

## 7. Hospital invoice / QR verification

The code decodes QR codes from rendered pages using OpenCV. It also checks invoice numbers against:

1. Local verified invoice cache: `app/seed_data/verified_invoices.json`
2. External hospital verification provider:

```env
HOSPITAL_API_BASE_URL=https://your-hospital-gateway.example.com
HOSPITAL_API_TOKEN=replace-me
```

Expected provider contract:

```http
POST /verify-invoice
```

Payload:

```json
{
  "invoice_numbers": ["INV24060910/0R"],
  "hospital_name": "SIDARTH HOSPITALS",
  "dates": ["22/01/2024"],
  "amount": 12500,
  "uhid_numbers": ["OP24024520"]
}
```

---

## 8. Signature and stamp matching

Add verified reference images here:

```text
app/seed_data/reference_signatures/
app/seed_data/reference_stamps/
```

Example:

```text
app/seed_data/reference_signatures/dr_sidarth_reddy.png
app/seed_data/reference_stamps/sidarth_hospitals_stamp.png
```

The system crops likely signature/stamp regions from uploaded pages and compares them using perceptual hashes. For stronger accuracy, train a Siamese network or CLIP-style embedding model using your verified samples.

---

## 9. Main project structure

```text
app/
├── api/                  # UI/API routes and schemas
├── core/                 # config + scoring
├── db/                   # SQLAlchemy models/database
├── services/             # pipeline modules
│   ├── ocr_service.py
│   ├── forensic_service.py
│   ├── hospital_service.py
│   ├── doctor_service.py
│   ├── signature_stamp_service.py
│   ├── medical_service.py
│   ├── behavior_service.py
│   ├── message_service.py
│   └── pipeline.py
├── storage/              # MinIO/local object storage
├── workers/              # Celery app/tasks
├── templates/            # client-friendly UI
└── seed_data/            # known doctors, invoices, visual references
```

---

## 10. API endpoints

```http
POST /api/claims/upload
GET  /api/claims
GET  /api/claims/{claim_id}
GET  /api/claims/{claim_id}/owner-message
```

---

## 11. Production deployment notes

For real production:

- Use PostgreSQL, not SQLite.
- Use MinIO/S3 with bucket lifecycle and encryption.
- Run at least one web container and one or more Celery workers.
- Keep `SHOW_DEBUG_JSON=false` for client-facing deployments.
- Put API keys in a secret manager, not `.env` committed to GitHub.
- Add Alembic migrations before frequent schema changes.
- Add authentication/RBAC before external use.
- Log every decision in `audit_logs`.
- Treat HIGH/MEDIUM risk as manual review, not automatic rejection.

---

## 12. Limitations that need real data

These modules are production-ready in structure, but become truly accurate only after you provide real verified data:

- NMC/state council doctor registry access or verified doctor master
- Hospital invoice verification agreements/API
- Verified doctor signature samples
- Verified clinic/hospital stamp samples
- Real fraudulent and genuine bill dataset for model training

