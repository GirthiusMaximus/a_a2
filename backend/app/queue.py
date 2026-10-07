"""Queue abstraction: RQ/Redis when REDIS_URL is set, inline thread pool otherwise."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

REDIS_URL = os.environ.get("REDIS_URL", "")

_executor: ThreadPoolExecutor | None = None
_rq_queue = None


def _get_rq():
    global _rq_queue
    if _rq_queue is None:
        from redis import Redis
        from rq import Queue

        _rq_queue = Queue(
            "generation",
            connection=Redis.from_url(REDIS_URL),
            default_timeout=1800,
        )
    return _rq_queue


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        workers = int(os.environ.get("INLINE_WORKERS", "2"))
        _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gen")
    return _executor


def enqueue_generation(job_id: str) -> None:
    from .tasks import run_generation

    if REDIS_URL:
        _get_rq().enqueue(run_generation, job_id, job_timeout=1800)
    else:
        _get_executor().submit(run_generation, job_id)


def queue_depth() -> int:
    if REDIS_URL:
        try:
            return _get_rq().count
        except Exception:  # noqa: BLE001
            return -1
    ex = _get_executor()
    return ex._work_queue.qsize()  # noqa: SLF001
