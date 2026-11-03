"""Optional Celery worker (PROCESSING_MODE=celery). Start with: celery -A app.workers.celery_app worker -c 1"""
from celery import Celery

from app.core.config import get_settings

celery = Celery("invoice_engine", broker=get_settings().celery_broker_url)
celery.conf.task_acks_late = True
celery.conf.worker_prefetch_multiplier = 1


@celery.task(name="process_document_job", bind=True, max_retries=0)
def process_document_job(self, job_id: str):
    from app.workers.document_tasks import run_job
    run_job(job_id)
