"""Generation job executed by workers (RQ worker container, or inline thread)."""
from __future__ import annotations

import json
import time
import traceback

import numpy as np

from rustworld import build_world, save_map_bytes
from rustworld.generation import Recipe, generate
from rustworld.heightmap_io import export_png16, export_raw16, import_heightmap
from rustworld.render import (
    animal_spawn_mask,
    ore_spawn_mask,
    player_spawn_mask,
    png_bytes,
    render_biome_image,
    render_map_image,
    render_mask_overlay,
)

from . import store


def _height_rgb_png(height01: np.ndarray) -> bytes:
    """16-bit height packed into R (high byte) + G (low byte) for the 3D viewer."""
    from PIL import Image

    h = np.clip(height01, 0.0, 1.0)
    v = (h * 65535.0 + 0.5).astype(np.uint16)
    rgb = np.zeros((*v.shape, 3), dtype=np.uint8)
    rgb[..., 0] = (v >> 8).astype(np.uint8)
    rgb[..., 1] = (v & 0xFF).astype(np.uint8)
    return png_bytes(Image.fromarray(rgb[::-1]))


def run_generation(job_id: str) -> None:
    d = store.job_dir(job_id)
    try:
        recipe_dict = json.loads((d / "recipe.json").read_text())
        store.write_status(job_id, state="running", progress=0.01, message="Starting")

        heightmap = None
        upload_id = recipe_dict.get("upload_id")
        if upload_id:
            path = store.find_upload(upload_id)
            if path is None:
                raise ValueError(f"uploaded heightmap {upload_id} not found")
            heightmap = import_heightmap(path.read_bytes(), path.name)

        recipe = Recipe(
            size=recipe_dict["size"],
            seed=recipe_dict["seed"],
            theme=recipe_dict.get("theme", "classic"),
            land_ratio=recipe_dict.get("land_ratio", 0.45),
            mountain_scale=recipe_dict.get("mountain_scale", 1.0),
            beach_width=recipe_dict.get("beach_width", 1.0),
            river_density=recipe_dict.get("river_density", 1.0),
            erosion=recipe_dict.get("erosion", True),
            biome_blacklist=recipe_dict.get("biome_blacklist", []),
            topology_blacklist=recipe_dict.get("topology_blacklist", []),
            water_level_offset=recipe_dict.get("water_level_offset", 0.0),
            heightmap=heightmap,
        )

        last_write = [0.0]

        def progress(frac: float, msg: str) -> None:
            now = time.time()
            if now - last_write[0] > 0.3 or frac >= 1.0:
                last_write[0] = now
                store.write_status(job_id, progress=round(0.05 + frac * 0.7, 3), message=msg)

        result = generate(recipe, progress)

        store.write_status(job_id, progress=0.78, message="Serializing .map")
        world = build_world(
            result.size, result.height01, result.water01,
            result.splat, result.biome, result.topology,
        )
        (d / "map.map").write_bytes(save_map_bytes(world))

        store.write_status(job_id, progress=0.85, message="Rendering previews")
        # margin 0 so the preview spans exactly the map extent — keeps the
        # spawn/biome overlays and the 3D drape texture pixel-aligned
        preview = render_map_image(
            result.size, result.height01, result.splat, result.water01,
            image_res=int(np.clip(result.size // 2, 512, 1600)),
            ocean_margin_frac=0.0,
        )
        preview.save(d / "preview.png")
        render_biome_image(result.biome).save(d / "biome.png")

        store.write_status(job_id, progress=0.92, message="Rendering overlays")
        render_mask_overlay(player_spawn_mask(result.topology), (64, 220, 100, 160)).save(
            d / "overlay_player_spawns.png")
        render_mask_overlay(ore_spawn_mask(result.topology), (255, 170, 40, 150)).save(
            d / "overlay_ore.png")
        render_mask_overlay(animal_spawn_mask(result.topology), (235, 80, 60, 110)).save(
            d / "overlay_animals.png")

        store.write_status(job_id, progress=0.96, message="Exporting heightmaps")
        (d / "heightmap16.png").write_bytes(export_png16(result.height01))
        (d / "heightmap.raw").write_bytes(export_raw16(result.height01))
        (d / "height_rgb.png").write_bytes(_height_rgb_png(result.height01))

        store.write_status(
            job_id, state="done", progress=1.0, message="Complete",
            stats=result.stats,
        )
    except Exception as exc:  # noqa: BLE001
        store.write_status(
            job_id, state="failed", message="Generation failed",
            error=f"{exc}\n{traceback.format_exc(limit=5)}",
        )
        raise
