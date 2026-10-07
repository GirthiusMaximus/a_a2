import { useState } from "react";
import { Job, api } from "../api";
import Viewer3D from "./Viewer3D";

interface Props {
  job: Job;
  onDelete: (id: string) => void;
}

const OVERLAYS = [
  { key: "overlay_player_spawns.png", label: "Player spawns", color: "#40dc64" },
  { key: "overlay_ore.png", label: "Ore nodes", color: "#ffaa28" },
  { key: "overlay_animals.png", label: "Animals", color: "#eb503c" },
  { key: "overlay_monuments.png", label: "Monuments & roads", color: "#ff5a5a" },
] as const;

const DOWNLOADS = [
  { key: "map.map", label: ".map file" },
  { key: "heightmap16.png", label: "Heightmap PNG (16-bit)" },
  { key: "heightmap.raw", label: "Heightmap RAW" },
  { key: "preview.png", label: "Preview PNG" },
  { key: "recipe.json", label: "Recipe JSON" },
  { key: "monuments.json", label: "Monuments JSON" },
] as const;

export default function MapViewer({ job, onDelete }: Props) {
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const [base, setBase] = useState<"preview" | "biome" | "height">("preview");
  const [overlays, setOverlays] = useState<string[]>([]);

  const done = job.state === "done";
  const stats = (job.stats ?? {}) as Record<string, any>;
  const recipe = (job.recipe ?? {}) as Record<string, any>;

  const baseImg =
    base === "biome" ? "biome.png" :
    base === "height" ? "heightmap16.png" : "preview.png";

  const toggleOverlay = (k: string) =>
    setOverlays((o) => (o.includes(k) ? o.filter((x) => x !== k) : [...o, k]));

  return (
    <div className="viewer">
      <div className="toolbar">
        <strong style={{ fontSize: 15 }}>
          {recipe.name || recipe.theme || "Map"}{" "}
          <span style={{ color: "var(--muted)", fontWeight: 400 }}>
            · {recipe.size}m · seed {recipe.seed}
          </span>
        </strong>
        <span className={`state ${job.state}`}>{job.state}</span>
        <div className="spacer" />
        {done && (
          <>
            <button className={mode === "2d" ? "small" : "small ghost"} onClick={() => setMode("2d")}>2D</button>
            <button className={mode === "3d" ? "small" : "small ghost"} onClick={() => setMode("3d")}>3D</button>
          </>
        )}
        <button className="small ghost" onClick={() => onDelete(job.id)}>Delete</button>
      </div>

      {job.state === "failed" && <div className="error-box">{job.error}</div>}

      {(job.state === "queued" || job.state === "running") && (
        <div className="panel">
          <div>{job.message}…</div>
          <div className="progressbar"><div style={{ width: `${job.progress * 100}%` }} /></div>
        </div>
      )}

      {done && (
        <>
          {mode === "2d" && (
            <div className="toolbar">
              <button className={base === "preview" ? "small" : "small ghost"} onClick={() => setBase("preview")}>Map</button>
              <button className={base === "biome" ? "small" : "small ghost"} onClick={() => setBase("biome")}>Biomes</button>
              <button className={base === "height" ? "small" : "small ghost"} onClick={() => setBase("height")}>Heightmap</button>
              <span style={{ width: 12 }} />
              {OVERLAYS.map((o) => (
                <span key={o.key}
                  className={`chip ${overlays.includes(o.key) ? "on" : ""}`}
                  style={overlays.includes(o.key) ? { borderColor: o.color, color: o.color } : {}}
                  onClick={() => toggleOverlay(o.key)}>
                  {o.label}
                </span>
              ))}
            </div>
          )}

          <div className="canvas-wrap">
            {mode === "2d" ? (
              <>
                <img className="base" src={api.artifactUrl(job.id, baseImg)} alt="map preview" />
                {overlays.map((k) => (
                  <img key={k} className="overlay" src={api.artifactUrl(job.id, k)} alt={k} />
                ))}
              </>
            ) : (
              <Viewer3D jobId={job.id} exaggeration={1.6} />
            )}
          </div>

          <div className="toolbar">
            {DOWNLOADS.filter((dl) => job.artifacts.includes(dl.key)).map((dl) => (
              <a key={dl.key} className="dl" href={api.artifactUrl(job.id, dl.key)} download>
                ⬇ {dl.label}
              </a>
            ))}
          </div>

          <div className="stats">
            <div className="stat"><div className="k">Land</div><div className="v">{stats.land_percent}%</div></div>
            <div className="stat"><div className="k">Spawn area</div>
              <div className="v" style={{ color: stats.spawn_valid ? "var(--green)" : "var(--rust-light)" }}>
                {stats.spawn_valid ? `${((stats.spawn_area_m2 ?? 0) / 1e4).toFixed(1)} ha ✓` : "INVALID"}
              </div></div>
            <div className="stat"><div className="k">Peak height</div><div className="v">{stats.max_height_m}m</div></div>
            <div className="stat"><div className="k">Ocean depth</div><div className="v">{stats.ocean_depth_m}m</div></div>
            <div className="stat"><div className="k">Heightmap</div><div className="v">{stats.heightmap_resolution}px</div></div>
            {stats.monument_count > 0 && (
              <div className="stat"><div className="k">Monuments</div><div className="v">{stats.monument_count}</div></div>
            )}
            {stats.road_length_km > 0 && (
              <div className="stat"><div className="k">Roads</div><div className="v">{stats.road_length_km} km</div></div>
            )}
            {Object.entries(stats.biome_percent ?? {}).map(([k, v]) => (
              (v as number) > 0.5 && (
                <div className="stat" key={k}>
                  <div className="k">{k}</div><div className="v">{v as number}%</div>
                </div>
              )
            ))}
          </div>
          {Array.isArray(stats.monuments) && stats.monuments.length > 0 && (
            <div className="monument-list">
              <div className="k">Monuments placed</div>
              <div>
                {(stats.monuments as string[]).map((m) => (
                  <span className="chip static" key={m}>{m}</span>
                ))}
              </div>
            </div>
          )}

          <div className="hint">
            Drop the .map into your server's <code>maps/</code> folder (or serve it via
            <code> levelurl</code>), or open it directly in RustEdit. The 16-bit heightmap
            imports into RustEdit at {stats.heightmap_resolution}×{stats.heightmap_resolution}.
          </div>
        </>
      )}
    </div>
  );
}
