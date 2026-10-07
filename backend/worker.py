"""RQ worker entrypoint (Compose `worker` service)."""
import os

from redis import Redis
from rq import Queue, Worker

redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
conn = Redis.from_url(redis_url)

if __name__ == "__main__":
    worker = Worker([Queue("generation", connection=conn)], connection=conn)
    worker.work(with_scheduler=False)
