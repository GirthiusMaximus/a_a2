export interface Recipe {
  name: string;
  size: number;
  seed: number | null;
  theme: string;
  land_ratio: number;
  mountain_scale: number;
  beach_width: number;
  river_density: number;
  erosion: boolean;
  biome_blacklist: string[];
  topology_blacklist: string[];
  water_level_offset: number;
  upload_id: string | null;
  monuments: boolean;
  monument_density: number;
  monument_whitelist: string[] | null;
  monument_blacklist: string[];
  roads: boolean;
  ring_road: boolean;
}

export interface Theme {
  key: string;
  label: string;
  description: string;
  supports_rivers: boolean;
  barren: boolean;
  supports_monuments: boolean;
  supports_roads: boolean;
}

export interface Monument {
  key: string;
  name: string;
  category: string;
  radius: number;
  placement: string;
  biomes: string[];
  min_map_size: number;
  max_count: number;
  default_on: boolean;
  prefab: string;
  prefab_id: number;
  tags: string[];
}

export interface PlacedMonument {
  key: string;
  name: string;
  category: string;
  x: number;
  z: number;
  y: number;
  yaw: number;
  radius: number;
  prefab: string;
  prefab_id: number;
}

export interface Preset {
  key: string;
  label: string;
  description: string;
  recipe: Partial<Recipe>;
}

export interface Job {
  id: string;
  state: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string;
  created_at: number;
  updated_at: number;
  recipe?: Record<string, unknown>;
  stats?: Record<string, unknown>;
  error?: string;
  artifacts: string[];
}

export const defaultRecipe = (): Recipe => ({
  name: "",
  size: 3000,
  seed: null,
  theme: "classic",
  land_ratio: 0.45,
  mountain_scale: 1.0,
  beach_width: 1.0,
  river_density: 1.0,
  erosion: true,
  biome_blacklist: [],
  topology_blacklist: [],
  water_level_offset: 0,
  upload_id: null,
  monuments: true,
  monument_density: 1.0,
  monument_whitelist: null,
  monument_blacklist: [],
  roads: true,
  ring_road: true,
});

async function json<T>(resp: Promise<Response>): Promise<T> {
  const r = await resp;
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  themes: () => json<Theme[]>(fetch("/api/themes")),
  presets: () => json<Preset[]>(fetch("/api/presets")),
  monuments: () => json<Monument[]>(fetch("/api/monuments")),
  options: () =>
    json<{ biomes: string[]; topologies: string[] }>(fetch("/api/options")),
  jobs: () => json<Job[]>(fetch("/api/jobs")),
  job: (id: string) => json<Job>(fetch(`/api/jobs/${id}`)),
  createJob: (recipe: Recipe) =>
    json<Job>(
      fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe }),
      }),
    ),
  deleteJob: (id: string) =>
    json<{ deleted: string }>(fetch(`/api/jobs/${id}`, { method: "DELETE" })),
  upload: async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return json<{ upload_id: string; resolution: number[] }>(
      fetch("/api/upload", { method: "POST", body: fd }),
    );
  },
  artifactUrl: (jobId: string, name: string) =>
    `/api/jobs/${jobId}/artifacts/${name}`,
};
