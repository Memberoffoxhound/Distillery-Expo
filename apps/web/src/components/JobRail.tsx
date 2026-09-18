import { useEffect, useState } from "react";
import type { StageTiming } from "../hooks/useJobStream";
import { formatDuration } from "../lib/api";
import { STAGES, type StageName, type StageStatus } from "../types/events";

const labels: Record<StageName, string> = {
  ingest: "Ingest",
  shard: "Shard",
  teach: "Teach",
  train: "Train",
  export: "Export",
  eval: "Eval",
  flash: "Flash",
};

function elapsedSeconds(t: StageTiming, now: number): number | null {
  if (!t.startedAt) return null;
  const start = Date.parse(t.startedAt);
  if (!Number.isFinite(start)) return null;
  const end = t.endedAt ? Date.parse(t.endedAt) : now;
  if (!Number.isFinite(end)) return null;
  return Math.max(0, (end - start) / 1000);
}

function weightLabel(t: StageTiming): string | null {
  if (t.status === "pending") return null;
  if (t.status === "done" || t.status === "skipped") return "100%";
  if (t.status === "failed") return "fail";
  if (t.status === "gated") return "gate";
  if (t.weight > 0) return `${Math.round(t.weight * 100)}%`;
  return null;
}

export function JobRail({
  stageStatus,
  stageTiming,
  jobKind,
}: {
  stageStatus: Record<StageName, StageStatus>;
  stageTiming: Record<StageName, StageTiming>;
  jobKind?: "demo" | "ingest" | null;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const hasLive = STAGES.some((s) => {
      const st = stageStatus[s];
      return (st === "running" || st === "gated") && stageTiming[s]?.startedAt;
    });
    if (!hasLive) return;
    const id = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(id);
  }, [stageStatus, stageTiming]);

  // Ingest-only jobs: emphasize ingest; keep full rail visible but quieter for later stages
  const ingestOnly = jobKind === "ingest";

  return (
    <div className="rail" aria-label="Pipeline stages">
      {STAGES.map((s, i) => {
        const status = stageStatus[s];
        const timing = stageTiming[s];
        const elapsed = elapsedSeconds(timing, now);
        const weight = weightLabel(timing);
        const muted =
          ingestOnly && s !== "ingest" && status === "pending";

        return (
          <span key={s} style={{ display: "contents" }}>
            {i > 0 && <span className="rail-arrow">›</span>}
            <div
              className={`rail-step ${status}${muted ? " muted-step" : ""}`}
              title={timing.detail ?? undefined}
            >
              <span className="dot" />
              <span className="rail-step-main">
                <span className="rail-label">{labels[s]}</span>
                <span className="rail-meta">
                  {elapsed != null ? (
                    <span className="rail-time">{formatDuration(elapsed)}</span>
                  ) : (
                    <span className="rail-time idle">—</span>
                  )}
                  {weight != null && (
                    <span className="rail-weight">{weight}</span>
                  )}
                </span>
              </span>
              {(status === "running" || status === "gated") && timing.weight > 0 && (
                <span
                  className="rail-weight-bar"
                  style={{ width: `${Math.round(timing.weight * 100)}%` }}
                />
              )}
            </div>
          </span>
        );
      })}
    </div>
  );
}
