import { useRef, useState } from "react";
import { Monument, Recipe, Theme, api } from "../api";

interface Props {
  themes: Theme[];
  biomes: string[];
  monuments: Monument[];
  recipe: Recipe;
  onChange: (r: Recipe) => void;
  onSubmit: () => void;
  busy: boolean;
}

const BLACKLISTABLE_TOPO = ["swamp", "forest", "clutter", "decor", "river", "lake"];

export default function GeneratorForm({ themes, biomes, monuments, recipe, onChange, onSubmit, busy }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadInfo, setUploadInfo] = useState<string>("");

  const set = (patch: Partial<Recipe>) => onChange({ ...recipe, ...patch });
  const toggle = (list: string[], v: string) =>
    list.includes(v) ? list.filter((x) => x !== v) : [...list, v];

  const theme = themes.find((t) => t.key === recipe.theme);

  const handleUpload = async (file: File) => {
    setUploadInfo("Uploading…");
    try {
      const res = await api.upload(file);
      set({ upload_id: res.upload_id });
      setUploadInfo(`✓ ${file.name} (${res.resolution[0]}×${res.resolution[1]})`);
    } catch (e) {
      setUploadInfo(`Upload failed: ${e}`);
    }
  };

  return (
    <div className="panel">
      <h2>Generate a world</h2>

      <label className="field">
        <div className="lab"><b>Map name</b></div>
        <input
          type="text"
          placeholder="My Custom Map"
          value={recipe.name}
          onChange={(e) => set({ name: e.target.value })}
        />
      </label>

      <label className="field">
        <div className="lab"><b>Theme</b></div>
        <select value={recipe.theme} onChange={(e) => set({ theme: e.target.value })}>
          {themes.map((t) => (
            <option key={t.key} value={t.key}>{t.label}</option>
          ))}
        </select>
        {theme && <div className="hint" style={{ marginTop: 4 }}>{theme.description}</div>}
      </label>

      <div className="row">
        <label className="field">
          <div className="lab"><b>Size</b><span>{recipe.size}m</span></div>
          <input
            type="range" min={1000} max={6000} step={500}
            value={recipe.size}
            onChange={(e) => set({ size: Number(e.target.value) })}
          />
        </label>
        <label className="field">
          <div className="lab"><b>Seed</b><span>blank = random</span></div>
          <input
            type="number" min={0} max={2147483647}
            value={recipe.seed ?? ""}
            placeholder="random"
            onChange={(e) =>
              set({ seed: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </label>
      </div>

      <label className="field">
        <div className="lab"><b>Land coverage</b><span>{Math.round(recipe.land_ratio * 100)}%</span></div>
        <input type="range" min={0.15} max={0.75} step={0.05} value={recipe.land_ratio}
          onChange={(e) => set({ land_ratio: Number(e.target.value) })} />
      </label>

      <div className="row">
        <label className="field">
          <div className="lab"><b>Mountains</b><span>×{recipe.mountain_scale.toFixed(1)}</span></div>
          <input type="range" min={0.2} max={3} step={0.1} value={recipe.mountain_scale}
            onChange={(e) => set({ mountain_scale: Number(e.target.value) })} />
        </label>
        <label className="field">
          <div className="lab"><b>Beaches</b><span>×{recipe.beach_width.toFixed(2)}</span></div>
          <input type="range" min={0.25} max={3} step={0.25} value={recipe.beach_width}
            onChange={(e) => set({ beach_width: Number(e.target.value) })} />
        </label>
      </div>

      <div className="row">
        <label className="field">
          <div className="lab"><b>Rivers</b><span>×{recipe.river_density.toFixed(1)}</span></div>
          <input type="range" min={0} max={3} step={0.5} value={recipe.river_density}
            disabled={!theme?.supports_rivers}
            onChange={(e) => set({ river_density: Number(e.target.value) })} />
        </label>
        <label className="field" style={{ display: "flex", alignItems: "end", gap: 6 }}>
          <input type="checkbox" checked={recipe.erosion}
            onChange={(e) => set({ erosion: e.target.checked })} />
          <span style={{ fontSize: 12.5 }}>Erosion pass</span>
        </label>
      </div>

      <label className="field">
        <div className="lab"><b>Blacklist biomes</b></div>
        <div className="chips">
          {biomes.map((b) => (
            <span key={b}
              className={`chip ${recipe.biome_blacklist.includes(b) ? "on" : ""}`}
              onClick={() => set({ biome_blacklist: toggle(recipe.biome_blacklist, b) })}>
              {b}
            </span>
          ))}
        </div>
      </label>

      <label className="field">
        <div className="lab"><b>Blacklist features</b></div>
        <div className="chips">
          {BLACKLISTABLE_TOPO.map((t) => (
            <span key={t}
              className={`chip ${recipe.topology_blacklist.includes(t) ? "on" : ""}`}
              onClick={() => set({ topology_blacklist: toggle(recipe.topology_blacklist, t) })}>
              {t}
            </span>
          ))}
        </div>
      </label>


      <label className="field">
        <div className="lab">
          <b>Monuments &amp; roads</b>
          {!theme?.supports_monuments && <span>not available for this theme</span>}
        </div>
        <div className="row" style={{ marginTop: 2 }}>
          <label className="field" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={recipe.monuments}
              disabled={!theme?.supports_monuments}
              onChange={(e) => set({ monuments: e.target.checked })} />
            <span style={{ fontSize: 12.5 }}>Place monuments</span>
          </label>
          <label className="field" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={recipe.roads}
              disabled={!theme?.supports_roads}
              onChange={(e) => set({ roads: e.target.checked })} />
            <span style={{ fontSize: 12.5 }}>Build roads</span>
          </label>
        </div>
        <div className="row">
          <label className="field">
            <div className="lab"><b>Density</b><span>×{recipe.monument_density.toFixed(1)}</span></div>
            <input type="range" min={0} max={3} step={0.25} value={recipe.monument_density}
              disabled={!recipe.monuments || !theme?.supports_monuments}
              onChange={(e) => set({ monument_density: Number(e.target.value) })} />
          </label>
          <label className="field" style={{ display: "flex", alignItems: "end", gap: 6 }}>
            <input type="checkbox" checked={recipe.ring_road}
              disabled={!recipe.roads || !theme?.supports_roads}
              onChange={(e) => set({ ring_road: e.target.checked })} />
            <span style={{ fontSize: 12.5 }}>Ring road</span>
          </label>
        </div>
      </label>

      {recipe.monuments && theme?.supports_monuments && monuments.length > 0 && (
        <label className="field">
          <div className="lab">
            <b>Monument selection</b>
            <span>{recipe.monument_blacklist.length > 0
              ? `${recipe.monument_blacklist.length} excluded`
              : "defaults"}</span>
          </div>
          <div className="chips scroll">
            {monuments
              .filter((m) => recipe.monument_whitelist === null ? m.default_on : true)
              .map((m) => {
                const off = recipe.monument_blacklist.includes(m.key);
                const tooBig = m.min_map_size > recipe.size;
                return (
                  <span key={m.key}
                    title={`${m.prefab}\nid ${m.prefab_id} · r${m.radius}m${tooBig ? " · needs a bigger map" : ""}`}
                    className={`chip ${off || tooBig ? "" : "on"}`}
                    style={tooBig ? { opacity: 0.4 } : {}}
                    onClick={() => set({ monument_blacklist: toggle(recipe.monument_blacklist, m.key) })}>
                    {m.name}
                  </span>
                );
              })}
          </div>
          <div className="hint">
            Click to exclude. Greyed-out monuments need a larger map. Repeatable
            monuments (quarries, gas stations, wells) scale with density.
          </div>
        </label>
      )}

      <label className="field">
        <div className="lab">
          <b>Base heightmap (optional)</b>
          {recipe.upload_id && (
            <span className="chip on" onClick={() => { set({ upload_id: null }); setUploadInfo(""); }}>
              clear ✕
            </span>
          )}
        </div>
        <input ref={fileRef} type="file" accept=".png,.raw,.r16"
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])} />
        <div className="hint">16-bit grayscale PNG or RAW. The theme's biomes, splats and topology are painted on top.</div>
        {uploadInfo && <div className="hint" style={{ color: "var(--green)" }}>{uploadInfo}</div>}
      </label>

      <button style={{ width: "100%", marginTop: 6 }} disabled={busy} onClick={onSubmit}>
        {busy ? "Queueing…" : "⚒ Queue generation"}
      </button>
    </div>
  );
}
