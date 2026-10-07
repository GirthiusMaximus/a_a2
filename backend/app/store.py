"""Filesystem-backed job store (shared between API and worker containers)."""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
UPLOAD_DIR = DATA_DIR / "uploads"

ARTIFACT_FILES = [
    "map.map",
    "preview.png",
    "biome.png",
    "heightmap16.png",
    "heightmap.raw",
    "height_rgb.png",
    "overlay_player_spawns.png",
    "overlay_ore.png",
    "overlay_animals.png",
    "overlay_roads.png",
    "recipe.json",
]


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    safe = "".join(c for c in job_id if c.isalnum() or c == "-")
    return JOBS_DIR / safe


def new_job(recipe: dict) -> str:
    ensure_dirs()
    job_id = uuid.uuid4().hex[:12]
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.json").write_text(json.dumps(recipe, indent=2))
    write_status(job_id, state="queued", progress=0.0, message="Queued",
                 created_at=time.time())
    return job_id


def read_status(job_id: str) -> dict | None:
    f = job_dir(job_id) / "status.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_status(job_id: str, **updates) -> dict:
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "status.json"
    current = read_status(job_id) or {"id": job_id, "created_at": time.time()}
    current.update(updates)
    current["id"] = job_id
    current["updated_at"] = time.time()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(current))
    tmp.replace(f)
    return current


def list_jobs(limit: int = 100) -> list[dict]:
    ensure_dirs()
    jobs = []
    for d in JOBS_DIR.iterdir():
        if not d.is_dir():
            continue
        status = read_status(d.name)
        if status:
            status["artifacts"] = available_artifacts(d.name)
            jobs.append(status)
    jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    return jobs[:limit]


def available_artifacts(job_id: str) -> list[str]:
    d = job_dir(job_id)
    return [name for name in ARTIFACT_FILES if (d / name).exists()]


def delete_job(job_id: str) -> bool:
    d = job_dir(job_id)
    if not d.exists():
        return False
    for f in d.iterdir():
        f.unlink()
    d.rmdir()
    return True


def save_upload(data: bytes, filename: str) -> str:
    ensure_dirs()
    upload_id = uuid.uuid4().hex[:12]
    ext = Path(filename).suffix.lower() or ".bin"
    (UPLOAD_DIR / f"{upload_id}{ext}").write_bytes(data)
    return upload_id


def find_upload(upload_id: str) -> Path | None:
    safe = "".join(c for c in upload_id if c.isalnum())
    for f in UPLOAD_DIR.glob(f"{safe}.*"):
        return f
    return None
