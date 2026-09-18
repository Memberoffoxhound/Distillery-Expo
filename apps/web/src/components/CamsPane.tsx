import type { DistilleryEvent } from "../types/events";

const CAMS = ["road", "wide", "driver"] as const;

export function CamsPane({ events }: { events: DistilleryEvent[] }) {
  const samples = events.filter((e) => e.kind === "sample");
  const latest = Object.fromEntries(
    CAMS.map((c) => [c, samples.filter((s) => s.payload.cam === c).at(-1)])
  );

  return (
    <div className="cam-grid">
      {CAMS.map((cam) => {
        const s = latest[cam];
        const active = Boolean(s);
        return (
          <div key={cam} className={`cam ${active ? "active" : ""}`}>
            {active && <div className="scan" />}
            <div className="label">{cam}</div>
            <div className="sub">
              {active ? String(s?.payload.label ?? "live stub") : "waiting…"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
