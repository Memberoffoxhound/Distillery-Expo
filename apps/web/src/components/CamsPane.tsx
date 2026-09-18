import { EmptyState } from "./EmptyState";
import type { DistilleryEvent } from "../types/events";

const CAMS = ["road", "wide", "driver"] as const;

type CamSample = {
  cam: string;
  label?: string;
  placeholder?: boolean;
  uri?: string | null;
  meta?: Record<string, unknown>;
};

function latestSamples(events: DistilleryEvent[]): Record<string, CamSample | undefined> {
  const samples = events.filter((e) => e.kind === "sample");
  return Object.fromEntries(
    CAMS.map((c) => {
      const camSamples = samples.filter((s) => s.payload.cam === c);
      const hit = camSamples[camSamples.length - 1];
      if (!hit) return [c, undefined];
      return [
        c,
        {
          cam: c,
          label: hit.payload.label as string | undefined,
          placeholder: Boolean(hit.payload.placeholder ?? true),
          uri: (hit.payload.uri as string | null | undefined) ?? null,
          meta: (hit.payload.meta as Record<string, unknown> | undefined) ?? {},
        },
      ];
    })
  );
}

function metaLine(s: CamSample): string {
  const m = s.meta ?? {};
  const bits: string[] = [];
  if (m.fixture || m.label === "fixture") bits.push("fixture");
  else if (typeof m.source === "string") bits.push(String(m.source));
  if (m.fps != null) bits.push(`${m.fps} fps`);
  if (m.width && m.height) bits.push(`${m.width}×${m.height}`);
  if (s.placeholder) bits.push("placeholder");
  return bits.join(" · ") || "sample ready";
}

export function CamsPane({ events }: { events: DistilleryEvent[] }) {
  const latest = latestSamples(events);
  const any = CAMS.some((c) => latest[c]);
  const routeId = CAMS.map((c) => latest[c]?.meta?.route_id).find(
    (v): v is string => typeof v === "string" && v.length > 0
  );
  const dongleId = CAMS.map((c) => latest[c]?.meta?.dongle_id).find(
    (v): v is string => typeof v === "string" && v.length > 0
  );

  if (!any) {
    return (
      <EmptyState
        title="Cams waiting"
        body="Road, wide, and driver surfaces appear when an ingest job emits sample events."
        hint="Connect/SSH/ADB a mici route from Ingest, then cams appear here."
      />
    );
  }

  return (
    <div className="cams-wrap">
      {(routeId || dongleId) && (
        <div className="cams-meta-bar">
          {dongleId ? (
            <span>
              <span className="k">dongle</span> {String(dongleId)}
            </span>
          ) : null}
          {routeId ? (
            <span>
              <span className="k">route</span> {String(routeId)}
            </span>
          ) : null}
        </div>
      )}
      <div className="cam-grid">
        {CAMS.map((cam) => {
          const s = latest[cam];
          const active = Boolean(s);
          return (
            <div key={cam} className={`cam ${active ? "active" : ""}`}>
              {active && <div className="scan" />}
              <div className="label">{cam}</div>
              <div className="sub">
                {active
                  ? String(s?.label ?? metaLine(s!))
                  : "waiting for sample…"}
              </div>
              {active && (
                <div className="cam-meta">{metaLine(s!)}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
