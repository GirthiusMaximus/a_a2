"""API schemas."""
from __future__ import annotations

import random
from typing import Optional

from pydantic import BaseModel, Field


class RecipeModel(BaseModel):
    name: str = ""
    size: int = Field(3000, ge=1000, le=6000)
    seed: Optional[int] = Field(None, ge=0, le=2147483647)
    theme: str = "classic"
    land_ratio: float = Field(0.45, ge=0.1, le=0.9)
    mountain_scale: float = Field(1.0, ge=0.2, le=3.0)
    beach_width: float = Field(1.0, ge=0.25, le=3.0)
    river_density: float = Field(1.0, ge=0.0, le=3.0)
    erosion: bool = True
    biome_blacklist: list[str] = Field(default_factory=list)
    topology_blacklist: list[str] = Field(default_factory=list)
    water_level_offset: float = Field(0.0, ge=-30.0, le=30.0)
    upload_id: Optional[str] = None  # use an uploaded heightmap as the base
    # --- monuments & roads (phase 3) ---
    monuments: bool = True
    monument_density: float = Field(1.0, ge=0.0, le=3.0)
    monument_whitelist: Optional[list[str]] = None   # None = catalogue default
    monument_blacklist: list[str] = Field(default_factory=list)
    roads: bool = True
    ring_road: bool = True

    def resolved_seed(self) -> int:
        return self.seed if self.seed is not None else random.randint(0, 2147483647)


class JobCreate(BaseModel):
    recipe: RecipeModel


class JobInfo(BaseModel):
    id: str
    state: str                   # queued | running | done | failed
    progress: float = 0.0
    message: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    recipe: Optional[dict] = None
    stats: Optional[dict] = None
    error: Optional[str] = None
    artifacts: list[str] = Field(default_factory=list)
