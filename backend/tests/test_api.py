"""API end-to-end test (inline queue, tiny map)."""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REDIS_URL", "")
    # reload store with patched env
    import importlib

    from app import store as store_mod
    importlib.reload(store_mod)
    from app import main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_full_job_flow(client):
    assert client.get("/api/health").json()["ok"]
    themes = client.get("/api/themes").json()
    assert any(t["key"] == "classic" for t in themes)
    assert len(client.get("/api/presets").json()) >= 5

    resp = client.post("/api/jobs", json={"recipe": {
        "size": 1000, "seed": 404, "theme": "circular_isle", "name": "test isle",
    }})
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["id"]

    deadline = time.time() + 180
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()
        if status["state"] in ("done", "failed"):
            break
        time.sleep(1)
    assert status and status["state"] == "done", status
    assert status["stats"]["spawn_valid"]
    for artifact in ("map.map", "preview.png", "heightmap16.png", "overlay_player_spawns.png"):
        assert artifact in status["artifacts"]
        r = client.get(f"/api/jobs/{job_id}/artifacts/{artifact}")
        assert r.status_code == 200
        assert len(r.content) > 500

    # .map artifact must itself round-trip through the codec
    from rustworld import load_map_bytes
    world, version = load_map_bytes(
        client.get(f"/api/jobs/{job_id}/artifacts/map.map").content)
    assert version == 10
    assert world.size == 1000
    assert {m.name for m in world.maps} >= {"terrain", "height", "water", "splat",
                                            "biome", "alpha", "topology"}


def test_upload_flow(client):
    from rustworld.heightmap_io import export_png16

    hm = np.linspace(0.45, 0.6, 129 * 129, dtype=np.float32).reshape(129, 129)
    png = export_png16(hm)
    r = client.post("/api/upload", files={"file": ("hm.png", png, "image/png")})
    assert r.status_code == 200, r.text
    upload_id = r.json()["upload_id"]

    resp = client.post("/api/jobs", json={"recipe": {
        "size": 1000, "seed": 7, "theme": "classic", "upload_id": upload_id,
    }})
    assert resp.status_code == 200, resp.text


def test_bad_inputs(client):
    assert client.post("/api/jobs", json={"recipe": {"theme": "nope"}}).status_code == 400
    assert client.post("/api/jobs", json={"recipe": {"size": 99}}).status_code == 422
    assert client.get("/api/jobs/doesnotexist").status_code == 404
    assert client.get("/api/jobs/x/artifacts/evil.txt").status_code == 404
