from app.db.database import SessionLocal
from app.db.models import Claim
from app.services.pipeline import run_claim_pipeline
from app.workers.celery_app import celery_app


@celery_app.task(name="process_claim")
def process_claim(claim_id: str) -> dict:
    db = SessionLocal()
    try:
        claim = db.query(Claim).filter(Claim.claim_id == claim_id).first()
        if not claim:
            return {"status": "not_found", "claim_id": claim_id}
        run_claim_pipeline(db, claim)
        return {"status": "completed", "claim_id": claim_id}
    finally:
        db.close()
