# Workers

Celery worker and scheduler code lives in `backend/app/workers` so the API, worker, and scheduler share one versioned Python image. Compose starts dedicated `webnovel_worker` and `webnovel_scheduler` containers with the isolated Redis broker.
