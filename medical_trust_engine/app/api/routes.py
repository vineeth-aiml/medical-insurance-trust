from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.schemas import ClaimDetailOut, ClaimOut
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Claim
from app.services.audit_service import audit
from app.services.pdf_service import store_upload
from app.services.pipeline import analysis_to_dict, run_claim_pipeline

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _enqueue_or_run(db: Session, claim: Claim):
    if settings.async_processing:
        try:
            from app.workers.tasks import process_claim
            process_claim.delay(claim.claim_id)
            claim.status = "QUEUED"
            audit(db, "claim_queued", claim_id=claim.claim_id)
            db.commit()
            db.refresh(claim)
            return claim
        except Exception as exc:
            # Production should alert on queue failure; for local safety, fall back to sync.
            audit(db, "queue_failed_sync_fallback", claim_id=claim.claim_id, error=str(exc))
    return run_claim_pipeline(db, claim)


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/claims", response_class=HTMLResponse)
def claims_page(request: Request, db: Session = Depends(get_db)):
    claims = db.query(Claim).order_by(Claim.created_at.desc()).all()
    return templates.TemplateResponse("claims.html", {"request": request, "claims": claims})


@router.get("/claims/{claim_id}/view", response_class=HTMLResponse)
def claim_detail_page(claim_id: str, request: Request, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.claim_id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return templates.TemplateResponse(
        "claim_detail.html",
        {"request": request, "claim": claim, "detail": analysis_to_dict(claim), "show_debug_json": settings.show_debug_json},
    )


@router.post("/upload", response_class=HTMLResponse)
def upload_from_form(employee_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        stored = store_upload(file.file, file.filename)
        claim = Claim(
            claim_id=stored.claim_id,
            employee_id=employee_id,
            file_name=stored.original_name,
            file_hash=stored.file_hash,
            file_path=str(stored.file_path),
            storage_backend=stored.storage_backend,
            storage_key=stored.storage_key,
            status="PROCESSING",
        )
        db.add(claim)
        audit(db, "claim_uploaded", claim_id=claim.claim_id, file_name=claim.file_name, storage_backend=stored.storage_backend)
        db.commit()
        db.refresh(claim)
        claim = _enqueue_or_run(db, claim)
        return RedirectResponse(url=f"/claims/{claim.claim_id}/view", status_code=303)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/claims/upload", response_model=ClaimOut)
def upload_claim(employee_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        stored = store_upload(file.file, file.filename)
        claim = Claim(
            claim_id=stored.claim_id,
            employee_id=employee_id,
            file_name=stored.original_name,
            file_hash=stored.file_hash,
            file_path=str(stored.file_path),
            storage_backend=stored.storage_backend,
            storage_key=stored.storage_key,
            status="PROCESSING",
        )
        db.add(claim)
        audit(db, "claim_uploaded_api", claim_id=claim.claim_id, file_name=claim.file_name)
        db.commit()
        db.refresh(claim)
        return _enqueue_or_run(db, claim)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/claims", response_model=list[ClaimOut])
def list_claims(db: Session = Depends(get_db)):
    return db.query(Claim).order_by(Claim.created_at.desc()).all()


@router.get("/api/claims/{claim_id}", response_model=ClaimDetailOut)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.claim_id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return analysis_to_dict(claim)


@router.get("/api/claims/{claim_id}/owner-message")
def get_owner_message(claim_id: str, db: Session = Depends(get_db)):
    claim = db.query(Claim).filter(Claim.claim_id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    detail = analysis_to_dict(claim)
    return {"claim_id": claim.claim_id, "message": detail.get("owner_message", "")}
