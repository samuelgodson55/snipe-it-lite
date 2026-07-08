"""
celery_app.py
-------------
The single Celery application instance shared by two different processes:

  1. The FastAPI `backend` container -- as a *producer* only. It imports
     `celery_app` + the task functions from `tasks/` and calls
     `.delay(...)` on them to enqueue a job, then immediately returns a
     task_id to the browser instead of blocking a request/response cycle
     on export generation (see api/audit.py).
  2. The `worker` container (docker-compose.yml) -- as the *consumer*. It
     runs `celery -A celery_app worker` and does the actual CSV/PDF
     generation work, completely out-of-band from any HTTP request.

Both processes point at the SAME Redis instance (`settings.REDIS_URL`),
which Celery uses as both the message broker (where queued jobs live until
a worker picks them up) and the result backend (where a finished job's
return value -- here, the exported file's bytes, base64-encoded -- is
stored until the API reads it back out for the frontend to download).

Task modules are imported explicitly in `include=[...]` below rather than
relying on Celery's autodiscovery, since this is a small, single-package
app with no Django-style "installed apps" list to scan.
"""

from celery import Celery

from config import settings
from logging_config import configure_logging

# The `worker` container runs this module directly (`celery -A celery_app
# worker`) rather than importing main.py, so nothing else calls
# `configure_logging()` for it -- do it here instead. Safe to also run a
# second time when the `backend` API container imports this module (as a
# producer): `configure_logging()` clears/replaces handlers rather than
# stacking them, so it never causes duplicate log lines either way.
configure_logging(settings)

celery_app = Celery(
    "snipeit_lite",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["tasks.export_tasks"],
)

celery_app.conf.update(
    # Store each task's return value (or exception) for
    # EXPORT_RESULT_TTL_SECONDS after it finishes, then let Redis expire it
    # automatically -- we don't want finished export files (which can
    # contain a full copy of the audit ledger) sitting in Redis forever if
    # nobody downloads them.
    result_expires=settings.EXPORT_RESULT_TTL_SECONDS,
    # Tasks only ever take a plain dict of JSON-safe args in and return a
    # plain dict out (see tasks/export_tasks.py) -- keeping serialization
    # to JSON (rather than Celery's default pickle) means a compromised/
    # buggy worker or broker message can't deserialize into arbitrary
    # Python objects.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # A finished job's own status/result should update in Redis as soon as
    # the worker finishes it, not batched -- exports are a low-volume,
    # latency-sensitive ("did my export finish yet?") workload, not a
    # high-throughput one.
    task_track_started=True,
    # If a worker process dies mid-export (OOM, container restart, etc.),
    # don't silently redeliver the same job to another worker and risk it
    # running twice -- better to surface the failure and let the person
    # click "export" again.
    task_acks_late=False,
)
