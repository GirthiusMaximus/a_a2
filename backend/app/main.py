"""Rust World Generator — API."""
from __future__ import annotations

import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from rustworld.generation.themes import THEMES
from rustworld.monuments import MONUMENTS
from rustworld.layers import Biome, Topology

from . import queue, store
from .models import JobCreate, JobInfo
from .presets import PRESETS

app = FastAPI(title="Rust World Generator", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_TYPES = {
    ".map": "application/octet-stream",
    ".png": "image/png",
    ".raw": "application/octet-stream",
    ".json": "application/json",
}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "queue_depth": queue.queue_depth()}


@app.get("/api/themes")
def themes() -> list[dict]:
    return [
        {"key": t.key, "label": t.label, "description": t.description,
         "supports_rivers": t.rivers, "barren": t.barren,
         "supports_monuments": t.monuments, "supports_roads": t.roads,
         "default_land_ratio": t.land_ratio_default,
         "facepunch_tiers": t.facepunch_tiers}
        for t in THEMES.values()
    ]


@app.get("/api/monuments")
def monuments() -> list[dict]:
    """Monument catalogue: what can be placed, and what is on by default."""
    return [
        {"key": m.key, "name": m.name, "category": m.category,
         "radius": m.radius, "placement": m.placement,
         "biomes": list(m.biomes), "min_map_size": m.min_map_size,
         "max_count": m.max_count, "default_on": m.default_on,
         "prefab": m.path, "prefab_id": m.id, "tags": list(m.tags)}
        for m in sorted(MONUMENTS.values(), key=lambda s: (-s.radius, s.key))
    ]


@app.get("/api/options")
def options() -> dict:
    return {
        "biomes": [b.name.lower() for b in Biome],
        "topologies": [t.name.lower() for t in Topology],
        "sizes": {"min": 1000, "max": 6000, "default": 3000},
    }


@app.get("/api/presets")
def presets() -> list[dict]:
    return PRESETS


@app.post("/api/jobs", response_model=JobInfo)
def create_job(body: JobCreate) -> JobInfo:
    if body.recipe.theme not in THEMES:
        raise HTTPException(400, f"unknown theme '{body.recipe.theme}'")
    if body.recipe.upload_id and store.find_upload(body.recipe.upload_id) is None:
        raise HTTPException(400, f"upload '{body.recipe.upload_id}' not found")
    recipe = body.recipe.model_dump()
    recipe["seed"] = body.recipe.resolved_seed()
    job_id = store.new_job(recipe)
    store.write_status(job_id, recipe=recipe)
    queue.enqueue_generation(job_id)
    return JobInfo(**store.read_status(job_id))


@app.get("/api/jobs", response_model=list[JobInfo])
def list_jobs(limit: int = 100) -> list[JobInfo]:
    return [JobInfo(**j) for j in store.list_jobs(limit)]


@app.get("/api/jobs/{job_id}", response_model=JobInfo)
def get_job(job_id: str) -> JobInfo:
    status = store.read_status(job_id)
    if status is None:
        raise HTTPException(404, "job not found")
    status["artifacts"] = store.available_artifacts(job_id)
    return JobInfo(**status)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    if not store.delete_job(job_id):
        raise HTTPException(404, "job not found")
    return {"deleted": job_id}


@app.get("/api/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: str, name: str) -> FileResponse:
    if name not in store.ARTIFACT_FILES:
        raise HTTPException(404, "unknown artifact")
    path = store.job_dir(job_id) / name
    if not path.exists():
        raise HTTPException(404, "artifact not available")
    status = store.read_status(job_id) or {}
    recipe = status.get("recipe") or {}
    if name == "map.map":
        # Rust convention: <name>.<size>.<seed>.map
        label = (recipe.get("name") or recipe.get("theme") or "custom").replace(" ", "_")
        filename = f"{label}.{recipe.get('size', 0)}.{recipe.get('seed', 0)}.map"
    else:
        filename = f"{job_id}_{name}"
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(path.suffix, "application/octet-stream"),
        filename=filename,
    )


@app.post("/api/upload")
async def upload_heightmap(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if len(data) > 128 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    # validate it parses
    from rustworld.heightmap_io import import_heightmap

    try:
        hm = import_heightmap(data, file.filename or "upload.png")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"could not parse heightmap: {exc}") from exc
    upload_id = store.save_upload(data, file.filename or "upload.png")
    return {"upload_id": upload_id, "resolution": list(hm.shape)}
