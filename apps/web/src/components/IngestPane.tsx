import { useCallback, useEffect, useMemo, useState } from "react";
import type { DistilleryEvent, StageName } from "../types/events";
import {
  fetchDongle,
  fetchDiscover,
  fetchDiscoverDevices,
  fetchRoutes,
  formatRouteLength,
  postDiscoverConnect,
  type DiscoverDevice,
  type DiscoverOverview,
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

type DiscoverMode = "idle" | "lan" | "connect" | "fixture" | "auto";

/** Honest connection posture for a normal person — not env-var archaeology. */
function connectionState(
  dongle: DongleInfo | null,
  mode: DiscoverMode,
  scanning: boolean,
  listSource: string,
  routeCount: number
): { label: string; tone: string; detail: string } {
  if (scanning) {
    return {
      label: "Scanning…",
      tone: "scanning",
      detail:
        mode === "lan"
          ? "Looking for mici on LAN (ADB + SSH)."
          : mode === "connect"
            ? "Asking comma Connect for routes."
            : "Resolving routes…",
    };
  }
  if (!dongle) {
    return {
      label: "Offline",
      tone: "offline",
      detail: "API unreachable — is the control room on :8000?",
    };
  }

  const connectStatus = (dongle.connect_status ?? "").toLowerCase();
  const adbStatus = (dongle.adb_status ?? "").toLowerCase();
  const needsJwt =
    connectStatus === "needs_jwt" ||
    connectStatus === "needs-jwt" ||
    (!dongle.connect_available && mode === "connect");

  if (needsJwt) {
    return {
      label: "Needs JWT",
      tone: "needs-jwt",
      detail: "Connect needs COMMA_JWT / CONNECT_JWT — or use Find on LAN / fixture.",
    };
  }

  if (dongle.force_fixture && mode !== "lan" && mode !== "connect") {
    return {
      label: "Fixture",
      tone: "fixture",
      detail: "Offline fixture forced — labeled fallback, not a live mici.",
    };
  }

  const lanReady =
    dongle.ssh_available ||
    dongle.adb_available === true ||
    adbStatus === "found" ||
    adbStatus === "ready";

  if (mode === "lan" && routeCount === 0) {
    if (!lanReady && dongle.adb_available !== true && !dongle.ssh_available) {
      return {
        label: "Offline",
        tone: "offline",
        detail:
          "No ADB or SSH path yet. Craig’s lan_scan / adb_available will unlock this — fixture stays available.",
      };
    }
    return {
      label: "No devices",
      tone: "empty",
      detail: "LAN scan returned nothing. Pick fixture, or check ADB/SSH.",
    };
  }

  if (mode === "connect" && routeCount === 0 && dongle.connect_available) {
    return {
      label: "Connected",
      tone: "connected",
      detail: "Connect is up, but no routes listed for this dongle.",
    };
  }

  if (routeCount > 0 && (listSource === "connect" || listSource === "ssh")) {
    return {
      label: "Connected",
      tone: "connected",
      detail: `${routeCount} route${routeCount === 1 ? "" : "s"} via ${listSource}.`,
    };
  }

  if (listSource === "fixture" || mode === "fixture") {
    return {
      label: "Fixture",
      tone: "fixture",
      detail: "Showing labeled fixture routes — not a live device.",
    };
  }

  if (dongle.connect_available || lanReady) {
    return {
      label: "Ready",
      tone: "connected",
      detail: "Pick Find on LAN or Use Connect to list routes.",
    };
  }

  return {
    label: "Offline",
    tone: "offline",
    detail: "No Connect / ADB / SSH yet — fixture is the safe path.",
  };
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
  const [mode, setMode] = useState<DiscoverMode>("fixture");
  const [lanNote, setLanNote] = useState<string | null>(null);

  const [pickedDevice, setPickedDevice] = useState<string | null>(null);
  const [discover, setDiscover] = useState<DiscoverOverview | null>(null);
  const [jwtDraft, setJwtDraft] = useState("");

  const load = useCallback(async (source: RouteSource, nextMode?: DiscoverMode, deviceId?: string | null) => {
    setLoading(true);
    setListError(null);
    if (nextMode) setMode(nextMode);
    try {
      const [d, overview, adb, r] = await Promise.all([
        fetchDongle(),
        fetchDiscover().catch(() => null),
        fetchDiscoverDevices().catch(() => ({ devices: [] as DiscoverDevice[], adb_available: false })),
        fetchRoutes(source, 20, {
          device: deviceId ?? pickedDevice,
          ssh_host: null,
        }),
      ]);
      setDiscover(overview);
      const adbDevices = (adb.devices ?? overview?.devices?.devices ?? []) as DiscoverDevice[];
      const connect = overview?.connect;
      const ssh = overview?.ssh;
      const enriched: DongleInfo = {
        ...d,
        connect_available: Boolean(connect?.available ?? connect?.configured ?? d.connect_available),
        ssh_available: Boolean(ssh?.available ?? ssh?.configured ?? d.ssh_available),
        force_fixture: Boolean(overview?.fixture?.forced ?? d.force_fixture),
        connect_status: connect?.configured
          ? "connected"
          : connect?.available
            ? "needs_jwt"
            : "offline",
        adb_available: Boolean(adb.adb_available ?? overview?.devices?.adb_available),
        adb_status: (adb.devices ?? []).length > 0 ? "found" : "missing",
        devices: adbDevices.map((x) => ({
          id: x.id,
          name: x.model ?? x.name ?? x.id,
          kind: x.transport === "tcp" || x.transport === "usb" ? "adb" : (x.kind ?? "adb"),
          online: String(x.state ?? "").toLowerCase() === "device",
          ...x,
        })),
      };
      setDongle(enriched);
      setRoutes(r.routes);
      setListSource(r.source);
      setPrefer(source);
      setSelected((prev) => {
        if (prev && r.routes.some((x) => x.route_id === prev)) return prev;
        return r.routes[0]?.route_id ?? null;
      });

      if (nextMode === "lan" || source === "ssh" || source === "auto") {
        if (adbDevices.length > 0) {
          setLanNote(
            `${adbDevices.length} ADB device${adbDevices.length === 1 ? "" : "s"} via GET /discover/devices — pick one, then a route.`
          );
        } else if (!enriched.ssh_available && r.routes.length === 0) {
          setLanNote(
            "No ADB devices and SSH not configured. Use Connect JWT or fixture."
          );
        } else if (r.routes.length === 0) {
          setLanNote("Discovery ok, but no routes returned. Try Connect or fixture.");
        } else {
          setLanNote(null);
        }
      } else if (nextMode === "connect") {
        if (!connect?.configured) {
          setLanNote("Connect needs a JWT — paste below or POST /discover/connect.");
        } else {
          setLanNote(null);
        }
      } else {
        setLanNote(null);
      }
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Could not load routes");
      setRoutes([]);
      setLanNote(null);
    } finally {
      setLoading(false);
    }
  }, [pickedDevice]);

  useEffect(() => {
    void load("fixture", "fixture");
  }, [load]);

  const findOnLan = () => {
    void load("ssh", "lan", pickedDevice);
  };

  const useConnect = () => {
    void load("connect", "connect");
  };

  const useFixture = () => {
    void load("fixture", "fixture");
  };

  const saveJwt = async () => {
    const token = jwtDraft.trim();
    if (!token) return;
    setLoading(true);
    try {
      await postDiscoverConnect(token, true);
      setJwtDraft("");
      await load("connect", "connect");
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Connect JWT failed");
    } finally {
      setLoading(false);
    }
  };

  const pickDevice = (id: string) => {
    setPickedDevice(id);
    void load(prefer === "fixture" ? "ssh" : prefer, "lan", id);
  };

  const conn = useMemo(
    () => connectionState(dongle, mode, loading, listSource, routes.length),
    [dongle, mode, loading, listSource, routes.length]
  );

  const metrics = latestMetrics(events, "ingest");
  const frac = progressOf(events, "ingest");
  const ingestActive = events.some(
    (e) => e.stage === "ingest" && (e.kind === "stage" || e.kind === "progress")
  );

  const discoveredDevices = dongle?.devices ?? [];
  const connectConfigured = Boolean(discover?.connect?.configured);

  return (
    <div className="ingest-pane">
      <div className="ingest-head">
        <div className="ingest-dongle">
          <span className="k">dongle</span>
          <span className="v mono">{dongle?.dongle_id ?? "…"}</span>
          <span className={`conn-chip tone-${conn.tone}`} title={conn.detail}>
            {conn.label}
          </span>
          <span className="source-chip" title="Resolved list source">
            {listSource}
          </span>
        </div>
        <div className="ingest-cred" aria-label="Route source availability">
          {dongle && (
            <>
              <span
                className={dongle.connect_available ? "ok" : "off"}
                title={
                  dongle.connect_available
                    ? "comma Connect available"
                    : "Connect unavailable — needs JWT"
                }
              >
                Connect
              </span>
              <span
                className={dongle.ssh_available ? "ok" : "off"}
                title={dongle.ssh_available ? "SSH available" : "SSH not configured"}
              >
                SSH
              </span>
              <span
                className={
                  dongle.adb_available === true ||
                  (dongle.adb_status ?? "").toLowerCase() === "found" ||
                  (dongle.adb_status ?? "").toLowerCase() === "ready"
                    ? "ok"
                    : "off"
                }
                title={
                  dongle.adb_available === true
                    ? "ADB on LAN available"
                    : "ADB discovery pending (Craig)"
                }
              >
                ADB
              </span>
              <span className="fixture-chip" title="Labeled offline fallback — never looks live">
                fixture
              </span>
            </>
          )}
        </div>
      </div>

      <p className="ingest-conn-detail muted">{conn.detail}</p>

      <div className="ingest-actions primary-row">
        <button
          className="primary"
          disabled={loading}
          onClick={findOnLan}
          title="GET /discover + /discover/devices, then /routes?source=ssh&device=…"
        >
          Find mici on LAN
        </button>
        <button
          className="primary"
          disabled={loading}
          onClick={useConnect}
          title="GET /discover/connect + /routes?source=connect"
        >
          Use Connect
        </button>
      </div>

      {(mode === "connect" || (!connectConfigured && mode !== "fixture")) && (
        <div className="ingest-jwt-row">
          <input
            type="password"
            placeholder="comma Connect JWT"
            value={jwtDraft}
            onChange={(e) => setJwtDraft(e.target.value)}
            disabled={loading}
            aria-label="Connect JWT"
          />
          <button
            disabled={loading || !jwtDraft.trim()}
            onClick={() => void saveJwt()}
            title="POST /discover/connect"
          >
            Save JWT
          </button>
        </div>
      )}

      <div className="ingest-actions secondary-row">
        <button
          className="fixture-btn"
          disabled={busy || loading}
          onClick={() => onIngest({ source: "fixture" })}
          title="Labeled fixture ingest — POST /jobs/ingest {source:fixture}"
        >
          Ingest fixture
        </button>
        <button
          disabled={busy || loading || !selected}
          onClick={() => onIngest({ source: prefer, routeId: selected })}
          title="Ingest the selected route from the current source"
        >
          Ingest selected
        </button>
        <button
          disabled={loading}
          onClick={useFixture}
          title="List labeled fixture routes only"
        >
          Show fixture
        </button>
        <button
          disabled={loading}
          onClick={() => void load(prefer, mode)}
          title="Refresh route list"
        >
          Refresh
        </button>
      </div>

      {discoveredDevices.length > 0 && (
        <div className="device-picks" aria-label="Discovered devices">
          <span className="k">Devices</span>
          <div className="device-pick-list">
            {discoveredDevices.map((dev, i) => {
              const id = String(dev.id ?? dev.name ?? i);
              const kind = String(dev.kind ?? "device");
              const online = dev.online !== false;
              return (
                <button
                  key={id}
                  type="button"
                  className={`device-pick ${online ? "" : "off"}${pickedDevice === id ? " selected" : ""}`}
                  disabled={busy || !online}
                  aria-pressed={pickedDevice === id}
                  title={`Select discovered ${kind} → /routes?device=`}
                  onClick={() => pickDevice(id)}
                >
                  <span className="device-pick-name">
                    {String(dev.name ?? dev.id ?? "device")}
                  </span>
                  <span className="device-pick-kind mono">{kind}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {lanNote && <div className="ingest-note">{lanNote}</div>}

      {listError && (
        <div className="ingest-error">
          Routes unavailable ({listError}). Is the API on :8000?
        </div>
      )}

      <div className="route-list" role="listbox" aria-label="mici routes">
        {loading && (
          <EmptyState
            title={mode === "lan" ? "Scanning LAN…" : "Loading routes"}
            body={
              mode === "lan"
                ? "Looking for mici over ADB and SSH. Pick a found device — no manual IP dig."
                : mode === "connect"
                  ? "Asking comma Connect for routes on this dongle."
                  : "Asking the API for mici routes."
            }
          />
        )}
        {!loading && !listError && routes.length === 0 && mode === "lan" && (
          <EmptyState
            title="Nothing on LAN yet"
            body="No ADB or SSH routes found. Fixture stays the labeled fallback until a device appears."
            hint="GET /discover/devices + /routes?source=ssh&device=…"
          />
        )}
        {!loading && !listError && routes.length === 0 && mode === "connect" && (
          <EmptyState
            title={dongle?.connect_available ? "No Connect routes" : "Needs JWT"}
            body={
              dongle?.connect_available
                ? "Connect is available but returned an empty list for this dongle."
                : "comma Connect isn’t ready (JWT). Try Find on LAN or Show fixture."
            }
            hint="GET /routes?source=connect"
          />
        )}
        {!loading && !listError && routes.length === 0 && mode !== "lan" && mode !== "connect" && (
          <EmptyState
            title="No routes yet"
            body="Nothing listed for this source. Use Find on LAN, Use Connect, or Show fixture."
            hint="GET /routes?source=fixture"
          />
        )}
        {!loading &&
          routes.map((r) => {
            const active = selected === r.route_id;
            const fixture =
              r.source === "fixture" ||
              Boolean(r.meta?.fixture) ||
              r.meta?.label === "fixture" ||
              listSource === "fixture";
            return (
              <button
                key={r.route_id}
                type="button"
                role="option"
                aria-selected={active}
                className={`route-row ${active ? "selected" : ""} ${fixture ? "is-fixture" : ""}`}
                onClick={() => setSelected(r.route_id)}
                disabled={busy}
              >
                <div className="route-row-top">
                  <span className="route-name">{r.display_name}</span>
                  {fixture && (
                    <span className="badge badge-fixture" title="Labeled fallback — not live">
                      fixture
                    </span>
                  )}
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
