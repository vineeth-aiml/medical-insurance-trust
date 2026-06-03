from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "medical_trust_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(task_track_started=True, worker_prefetch_multiplier=1, task_acks_late=True)
