import { useCallback, useEffect, useState } from "react";
import type { DistilleryEvent, StageName } from "../types/events";
import {
  fetchDongle,
  fetchRoutes,
  formatRouteLength,
  type DongleInfo,
  type RouteSource,
  type RouteSummary,
} from "../lib/api";
import { EmptyState } from "./EmptyState";

function latestMetrics(events: DistilleryEvent[], stage?: StageName) {
  const map = new Map<string, { value: number; unit?: string }>();
  for (const ev of events) {
    if (ev.kind !== "metric") continue;
    if (stage && ev.stage !== stage) continue;
    map.set(String(ev.payload.name), {
      value: Number(ev.payload.value),
      unit: ev.payload.unit as string | undefined,
    });
  }
  return [...map.entries()];
}

function progressOf(events: DistilleryEvent[], stage: StageName): number {
  let f = 0;
  for (const ev of events) {
    if (ev.kind === "progress" && ev.stage === stage) {
      f = Number(ev.payload.fraction ?? 0);
    }
  }
  return f;
}

function shortRouteId(id: string): string {
  if (id.includes("|")) {
    const [dongle, rest] = id.split("|");
    return `${dongle.slice(0, 6)}…|${rest}`;
  }
  return id.length > 28 ? `${id.slice(0, 26)}…` : id;
}

export function IngestPane({
  events,
  busy,
  onIngest,
}: {
  events: DistilleryEvent[];
  busy: boolean;
  onIngest: (opts: { source: RouteSource; routeId?: string | null }) => void;
}) {
  const [dongle, setDongle] = useState<DongleInfo | null>(null);
  const [routes, setRoutes] = useState<RouteSummary[]>([]);
  const [listSource, setListSource] = useState<string>("—");
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [prefer, setPrefer] = useState<RouteSource>("fixture");

  const load = useCallback(async (source: RouteSource) => {
    setLoading(true);
    setListError(null);
    try {
      const [d, r] = await Promise.all([
        fetchDongle(),
        fetchRoutes(source, 20),
      ]);
      setDongle(d);
      setRoutes(r.routes);
      setListSource(r.source);
      setPrefer(source);
      setSelected((prev) => {
        if (prev && r.routes.some((x) => x.route_id === prev)) return prev;
        return r.routes[0]?.route_id ?? null;
      });
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Could not load routes");
      setRoutes([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load("fixture");
  }, [load]);

  const metrics = latestMetrics(events, "ingest");
  const frac = progressOf(events, "ingest");
  const ingestActive = events.some(
    (e) => e.stage === "ingest" && (e.kind === "stage" || e.kind === "progress")
  );

  return (
    <div className="ingest-pane">
      <div className="ingest-head">
        <div className="ingest-dongle">
          <span className="k">dongle</span>
          <span className="v mono">{dongle?.dongle_id ?? "…"}</span>
          <span className="source-chip" title="Resolved list source">
            {listSource}
          </span>
        </div>
        <div className="ingest-cred">
          {dongle && (
            <>
              <span className={dongle.connect_available ? "ok" : "off"}>
                Connect
              </span>
              <span className={dongle.ssh_available ? "ok" : "off"}>SSH</span>
              <span className="ok">fixture</span>
            </>
          )}
        </div>
      </div>

      <div className="ingest-actions">
        <button
          className="primary"
          disabled={busy || loading}
          onClick={() => onIngest({ source: "fixture" })}
          title="One-tap M1 path — POST /jobs/ingest {source:fixture}"
        >
          Ingest fixture
        </button>
        <button
          disabled={busy || loading || !selected}
          onClick={() => onIngest({ source: prefer, routeId: selected })}
        >
          Ingest selected
        </button>
        <button
          disabled={loading}
          onClick={() => void load(prefer)}
          title="Refresh route list"
        >
          Refresh
        </button>
        <select
          className="source-select"
          value={prefer}
          disabled={loading}
          onChange={(e) => {
            const s = e.target.value as RouteSource;
            void load(s);
          }}
          aria-label="Route source"
        >
          <option value="fixture">fixture</option>
          <option value="auto">auto</option>
          <option value="connect">connect</option>
          <option value="ssh">ssh</option>
        </select>
      </div>

      {listError && (
        <div className="ingest-error">
          Routes unavailable ({listError}). Is the API on :8000?
        </div>
      )}

      <div className="route-list" role="listbox" aria-label="mici routes">
        {loading && (
          <EmptyState
            title="Loading routes"
            body="Asking the API for mici routes on this dongle."
          />
        )}
        {!loading && !listError && routes.length === 0 && (
          <EmptyState
            title="No routes yet"
            body="Nothing listed for this source. Try fixture, or check Connect / SSH credentials."
            hint="GET /routes?source=fixture"
          />
        )}
        {!loading &&
          routes.map((r) => {
            const active = selected === r.route_id;
            const fixture =
              r.source === "fixture" ||
              Boolean(r.meta?.fixture) ||
              r.meta?.label === "fixture";
            return (
              <button
                key={r.route_id}
                type="button"
                role="option"
                aria-selected={active}
                className={`route-row ${active ? "selected" : ""}`}
                onClick={() => setSelected(r.route_id)}
                disabled={busy}
              >
                <div className="route-row-top">
                  <span className="route-name">{r.display_name}</span>
                  {fixture && <span className="badge">fixture</span>}
                </div>
                <div className="route-row-meta mono">
                  <span>{shortRouteId(r.route_id)}</span>
                  <span>{r.segment_count ?? 0} segs</span>
                  <span>{formatRouteLength(r.length_s)}</span>
                </div>
              </button>
            );
          })}
      </div>

      {(ingestActive || metrics.length > 0) && (
        <div className="ingest-progress">
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${frac * 100}%` }} />
          </div>
          {metrics.length === 0 ? (
            <div className="muted">Pulling route…</div>
          ) : (
            metrics.map(([k, { value, unit }]) => (
              <div key={k} className="metric-row">
                <span className="k">{k}</span>
                <span className="v">
                  {value}
                  {unit ? ` ${unit}` : ""}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
