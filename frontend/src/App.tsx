import { useCallback, useEffect, useMemo, useState } from "react";
import { Job, Preset, Recipe, Theme, api, defaultRecipe } from "./api";
import GeneratorForm from "./components/GeneratorForm";
import MapViewer from "./components/MapViewer";

export default function App() {
  const [themes, setThemes] = useState<Theme[]>([]);
  const [biomes, setBiomes] = useState<string[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [recipe, setRecipe] = useState<Recipe>(defaultRecipe());
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.themes().then(setThemes).catch((e) => setError(String(e)));
    api.options().then((o) => setBiomes(o.biomes)).catch(() => {});
    api.presets().then(setPresets).catch(() => {});
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const js = await api.jobs();
      setJobs(js);
    } catch { /* api offline */ }
  }, []);

  useEffect(() => {
    refreshJobs();
    const t = setInterval(refreshJobs, 1500);
    return () => clearInterval(t);
  }, [refreshJobs]);

  const submit = async (r: Recipe = recipe) => {
    setBusy(true);
    setError("");
    try {
      const job = await api.createJob(r);
      setSelected(job.id);
      await refreshJobs();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const runPreset = (p: Preset) => {
    const r = { ...defaultRecipe(), ...p.recipe } as Recipe;
    setRecipe(r);
    submit(r);
  };

  const deleteJob = async (id: string) => {
    await api.deleteJob(id).catch(() => {});
    if (selected === id) setSelected(null);
    refreshJobs();
  };

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selected) ?? null,
    [jobs, selected],
  );

  const activeCount = jobs.filter((j) => j.state === "queued" || j.state === "running").length;

  return (
    <>
      <header className="topbar">
        <h1>⚒ RUST <span>WORLD GENERATOR</span></h1>
        <span className="sub">procedural .map factory — RustEdit & server ready</span>
        <div style={{ flex: 1 }} />
        <span className="sub">{activeCount > 0 ? `${activeCount} job(s) in queue` : "queue idle"}</span>
      </header>

      <div className="layout">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <GeneratorForm
            themes={themes} biomes={biomes} recipe={recipe}
            onChange={setRecipe} onSubmit={() => submit()} busy={busy}
          />
          <div className="panel">
            <h2>Example maps</h2>
            <div className="presets">
              {presets.map((p) => (
                <div key={p.key} className="preset" onClick={() => runPreset(p)} title="Click to generate">
                  <div className="t">{p.label}</div>
                  <div className="d">{p.description}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {error && <div className="error-box">{error}</div>}

          {selectedJob ? (
            <div className="panel">
              <MapViewer job={selectedJob} onDelete={deleteJob} />
            </div>
          ) : (
            <div className="panel">
              <div className="empty">
                Queue a generation or pick an example map —<br />
                then select a job below to view and download it.
              </div>
            </div>
          )}

          <div className="panel">
            <h2>Generation queue</h2>
            <div className="jobs">
              {jobs.length === 0 && <div className="empty">No jobs yet.</div>}
              {jobs.map((j) => {
                const r = (j.recipe ?? {}) as Record<string, any>;
                return (
                  <div key={j.id}
                    className={`job ${selected === j.id ? "sel" : ""}`}
                    onClick={() => setSelected(j.id)}>
                    {j.artifacts.includes("preview.png") ? (
                      <img className="thumb" src={api.artifactUrl(j.id, "preview.png")} alt="" />
                    ) : (
                      <div className="thumb" />
                    )}
                    <div className="meta">
                      <div className="name">
                        {r.name || r.theme || j.id}
                        <span style={{ color: "var(--muted)", fontWeight: 400 }}>
                          {" "}· {r.size}m · seed {r.seed}
                        </span>
                      </div>
                      <div className="sub">{j.message}</div>
                      {(j.state === "running" || j.state === "queued") && (
                        <div className="progressbar"><div style={{ width: `${j.progress * 100}%` }} /></div>
                      )}
                    </div>
                    <span className={`state ${j.state}`}>{j.state}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
