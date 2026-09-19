import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DistilleryEvent, StageName } from "../types/events";
import {
  DEMO_DONGLE_ID,
  fetchDongle,
  fetchDiscover,
  fetchDiscoverDevices,
  fetchRoutes,
  formatRouteLength,
  isBannedDemoDongle,
  postDiscoverConnect,
  saveDongleId,
  saveDiscoverSsh,
  testDiscoverSsh,
  type ConnectScope,
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

/** One calm picker: Public routes | My Connect | SSH/ADB */
type SourceTab = "public" | "mine" | "lan";

function tabToFetch(tab: SourceTab): { source: RouteSource; scope?: ConnectScope; mode: SourceTab } {
  if (tab === "public") return { source: "connect", scope: "public", mode: "public" };
  if (tab === "mine") return { source: "connect", scope: "mine", mode: "mine" };
  return { source: "ssh", mode: "lan" };
}

function connectionState(
  dongle: DongleInfo | null,
  tab: SourceTab,
  scanning: boolean,
  listSource: string,
  routeCount: number,
  emptyReason: string | null
): { label: string; tone: string; detail: string } {
  if (scanning) {
    return {
      label: "Loading…",
      tone: "scanning",
      detail:
        tab === "public"
          ? "Browsing shared & public Connect drives."
          : tab === "mine"
            ? "Asking comma Connect for your dongle routes."
            : "Looking for mici on LAN (ADB + SSH).",
    };
  }
  if (!dongle) {
    return {
      label: "Offline",
      tone: "offline",
      detail: "API unreachable — is the control room on :8000?",
    };
  }

  if (emptyReason === "connect_unauthorized" || emptyReason === "connect_not_configured") {
    return {
      label: "Needs JWT",
      tone: "needs-jwt",
      detail: "Paste Connect JWT under Connection, then Save.",
    };
  }

  if (tab === "public" && routeCount === 0) {
    return {
      label: "No public hits",
      tone: "empty",
      detail: "No shared/public Connect routes yet — honest empty.",
    };
  }

  if (tab === "mine" && !(dongle.dongle_id || "").trim() && routeCount === 0) {
    return {
      label: "Needs Dongle",
      tone: "needs-jwt",
      detail: "Save Dongle under Connection, or switch to Public / SSH/ADB.",
    };
  }

  if (tab === "lan" && routeCount === 0) {
    if (listSource === "ssh" || dongle.ssh_available) {
      return {
        label: "SSH · 0 routes",
        tone: "empty",
        detail: "SSH ok · 0 routes under /data/media/0/realdata",
      };
    }
    return {
      label: "No devices",
      tone: "empty",
      detail: "No ADB/SSH path yet — open Connection to configure.",
    };
  }

  if (routeCount > 0) {
    return {
      label: "Ready",
      tone: "connected",
      detail: `${routeCount} route${routeCount === 1 ? "" : "s"} via ${listSource}${tab === "public" ? " · public" : ""}.`,
    };
  }

  return {
    label: "Ready",
    tone: "connected",
    detail: "Pick a source tab, then a route.",
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
  const [routesMessage, setRoutesMessage] = useState<string | null>(null);
  const [emptyReason, setEmptyReason] = useState<string | null>(null);
  const [tab, setTab] = useState<SourceTab>("public");
  const [lanNote, setLanNote] = useState<string | null>(null);

  const [pickedDevice, setPickedDevice] = useState<string | null>(null);
  const [discover, setDiscover] = useState<DiscoverOverview | null>(null);
  const [dongleDraft, setDongleDraft] = useState("");
  const [dongleOrigin, setDongleOrigin] = useState<"none" | "saved" | "adb" | "ssh" | "manual">("none");
  const dongleTouchedRef = useRef(false);
  const [jwtDraft, setJwtDraft] = useState("");
  const [sshHost, setSshHost] = useState("");
  const [sshUser, setSshUser] = useState("comma");
  const [sshPort, setSshPort] = useState("22");
  const [sshIdentity, setSshIdentity] = useState("");
  const [sshProbeNote, setSshProbeNote] = useState<string | null>(null);
  const [connOpen, setConnOpen] = useState(false);

  const applyRoutes = (source: RouteSource, r: Awaited<ReturnType<typeof fetchRoutes>>) => {
    const askedLive = source === "ssh" || source === "connect";
    const swappedToFixture = askedLive && r.source === "fixture";
    const shown = swappedToFixture ? [] : r.routes;
    setRoutes(shown);
    setListSource(swappedToFixture ? source : r.source);
    setRoutesMessage(
      swappedToFixture
        ? "SSH/Connect returned fixture unexpectedly — showing empty (live path only)."
        : r.message ?? null
    );
    setEmptyReason(swappedToFixture ? "refused_fixture_swap" : r.empty_reason ?? null);
    setSelected((prev) => {
      if (prev && shown.some((x) => x.route_id === prev)) return prev;
      return shown[0]?.route_id ?? null;
    });
    return shown;
  };

  const load = useCallback(
    async (nextTab: SourceTab, deviceId?: string | null) => {
      setLoading(true);
      setListError(null);
      setRoutesMessage(null);
      setEmptyReason(null);
      setTab(nextTab);
      const { source, scope } = tabToFetch(nextTab);
      try {
        const [d, overview, adb, r] = await Promise.all([
          fetchDongle(),
          fetchDiscover().catch(() => null),
          fetchDiscoverDevices().catch(() => ({
            devices: [] as DiscoverDevice[],
            adb_available: false,
          })),
          fetchRoutes(source, 20, {
            device: deviceId ?? pickedDevice,
            ssh_host: null,
            scope: scope ?? null,
          }),
        ]);
        setDiscover(overview);
        const adbDevices = (adb.devices ?? overview?.devices?.devices ?? []) as DiscoverDevice[];
        const connect = overview?.connect;
        const ssh = overview?.ssh;

        // Never surface banned demo id as configured
        let liveDongleId = (d.dongle_id || "").trim();
        if (isBannedDemoDongle(liveDongleId)) {
          liveDongleId = "";
        }

        const enriched: DongleInfo = {
          ...d,
          dongle_id: liveDongleId,
          configured: Boolean(liveDongleId),
          connect_available: Boolean(connect?.available ?? connect?.configured ?? d.connect_available),
          ssh_available: Boolean(ssh?.available ?? ssh?.configured ?? d.ssh_available),
          force_fixture: Boolean(overview?.fixture?.forced ?? d.force_fixture),
          connect_status: connect?.configured
            ? "connected"
            : connect?.available
              ? "needs_jwt"
              : "offline",
          adb_available: Boolean(adb.adb_available ?? overview?.devices?.adb_available),
          adb_status: (() => {
            const avail = Boolean(adb.adb_available ?? overview?.devices?.adb_available);
            const n = (adb.devices ?? []).length;
            if (!avail) return "not_on_path";
            return n > 0 ? "found" : "ready";
          })(),
          devices: adbDevices.map((x) => ({
            id: x.id,
            name: x.model ?? x.name ?? x.id,
            kind: x.transport === "tcp" || x.transport === "usb" ? "adb" : (x.kind ?? "adb"),
            online: String(x.state ?? "").toLowerCase() === "device",
            ...x,
          })),
        };
        setDongle(enriched);

        const suggestedRaw =
          overview?.suggested_dongle_id ?? (d as DongleInfo).suggested_dongle_id ?? null;
        let suggested =
          typeof suggestedRaw === "string" && suggestedRaw.trim() ? suggestedRaw.trim() : null;
        if (isBannedDemoDongle(suggested)) suggested = null;

        const discSourceRaw =
          overview?.discovered_from ??
          overview?.dongle_discovery_source ??
          (d as DongleInfo).discovered_from ??
          (d as DongleInfo).dongle_discovery_source ??
          null;
        const discSource =
          discSourceRaw === "ssh" ? "ssh" : discSourceRaw === "adb" ? "adb" : null;

        if (enriched.dongle_id) {
          setDongleDraft((prev) => (prev.trim() && !isBannedDemoDongle(prev) ? prev : enriched.dongle_id));
          if (!dongleTouchedRef.current) {
            setDongleOrigin((prev) => (prev === "manual" ? prev : "saved"));
          }
        } else if (suggested && !dongleTouchedRef.current) {
          setDongleDraft((prev) => (prev.trim() && !isBannedDemoDongle(prev) ? prev : suggested));
          if (discSource) setDongleOrigin(discSource);
        } else if (isBannedDemoDongle(dongleDraft)) {
          setDongleDraft("");
          setDongleOrigin("none");
        }

        const shouldAutoPersist =
          Boolean(suggested) &&
          !Boolean(enriched.configured) &&
          !(enriched.dongle_id || "").trim() &&
          !dongleTouchedRef.current &&
          !isBannedDemoDongle(suggested);

        if (shouldAutoPersist && suggested) {
          try {
            const saved = await saveDongleId(suggested, true);
            enriched.dongle_id = saved.dongle_id || suggested;
            enriched.configured = true;
            setDongle({ ...enriched });
            setDongleDraft(saved.dongle_id || suggested);
            if (discSource) setDongleOrigin(discSource);
            if (nextTab === "mine" || nextTab === "lan") {
              const r2 = await fetchRoutes(source, 20, {
                device: deviceId ?? pickedDevice,
                ssh_host: null,
                scope: scope ?? null,
              });
              applyRoutes(source, r2);
            }
          } catch {
            if (discSource) setDongleOrigin(discSource);
          }
        }

        applyRoutes(source, r);

        if (ssh?.host) {
          setSshHost((prev) => prev || String(ssh.host));
          if (ssh.user) setSshUser(String(ssh.user));
          if (ssh.port != null) setSshPort(String(ssh.port));
          if (ssh.identity_path) setSshIdentity(String(ssh.identity_path));
        } else {
          const suggestedHost = adbDevices.find((d) => d.suggested_host)?.suggested_host;
          if (suggestedHost) {
            setSshHost((prev) => (prev.trim() ? prev : String(suggestedHost)));
          }
        }

        if (nextTab === "lan") {
          if (r.message) setLanNote(r.message);
          else if (adbDevices.length > 0) {
            setLanNote(
              `${adbDevices.length} ADB device${adbDevices.length === 1 ? "" : "s"} — pick one, then a route.`
            );
          } else if (!enriched.ssh_available) {
            setLanNote("No ADB devices and SSH not configured — open Connection.");
          } else {
            setLanNote(null);
          }
        } else if (nextTab === "public" && !connect?.configured) {
          setLanNote("Public routes need a Connect JWT — open Connection.");
          setConnOpen(true);
        } else {
          setLanNote(null);
        }
      } catch (e) {
        setListError(e instanceof Error ? e.message : "Could not load routes");
        setRoutes([]);
        setRoutesMessage(null);
        setEmptyReason(null);
        setLanNote(null);
      } finally {
        setLoading(false);
      }
    },
    [pickedDevice, dongleDraft]
  );

  useEffect(() => {
    // Happy path: Public routes first (mici may be offline).
    void load("public");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveJwt = async () => {
    const token = jwtDraft.trim();
    if (!token) return;
    setLoading(true);
    try {
      await postDiscoverConnect(token, true);
      setJwtDraft("");
      await load(tab === "lan" ? "public" : tab);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Connect JWT failed");
    } finally {
      setLoading(false);
    }
  };

  const saveDongle = async () => {
    const id = dongleDraft.trim();
    if (!id) return;
    if (isBannedDemoDongle(id)) {
      setListError(`Demo dongle ${DEMO_DONGLE_ID.slice(0, 8)}… is banned — use a real id or Auto from ADB/SSH.`);
      setDongleDraft("");
      return;
    }
    setLoading(true);
    try {
      const info = await saveDongleId(id, true);
      dongleTouchedRef.current = false;
      setDongleOrigin("manual");
      setDongleDraft(info.dongle_id || id);
      await load("mine");
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Dongle ID save failed");
    } finally {
      setLoading(false);
    }
  };

  const saveSsh = async () => {
    const host = sshHost.trim();
    if (!host) return;
    setLoading(true);
    setSshProbeNote(null);
    try {
      const portNum = Number.parseInt(sshPort.trim() || "22", 10);
      await saveDiscoverSsh({
        host,
        user: sshUser.trim() || "comma",
        port: Number.isFinite(portNum) && portNum > 0 ? portNum : 22,
        identity_path: sshIdentity.trim() || null,
        persist: true,
      });
      await load("lan", pickedDevice);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "SSH config failed");
    } finally {
      setLoading(false);
    }
  };

  const testSsh = async () => {
    setSshProbeNote(null);
    setLoading(true);
    try {
      const host = sshHost.trim();
      if (host) {
        const portNum = Number.parseInt(sshPort.trim() || "22", 10);
        await saveDiscoverSsh({
          host,
          user: sshUser.trim() || "comma",
          port: Number.isFinite(portNum) && portNum > 0 ? portNum : 22,
          identity_path: sshIdentity.trim() || null,
          persist: true,
        });
      }
      const probe = await testDiscoverSsh();
      setSshProbeNote(probe.ok ? "SSH probe ok" : probe.error || "SSH probe failed");
      await load("lan", pickedDevice);
    } catch (e) {
      setSshProbeNote(e instanceof Error ? e.message : "SSH probe failed");
    } finally {
      setLoading(false);
    }
  };

  const pickDevice = (id: string) => {
    setPickedDevice(id);
    const fromDongle = (dongle?.devices ?? []).find((d) => String(d.id ?? "") === id) as
      | DiscoverDevice
      | undefined;
    const fromDiscover = (discover?.devices?.devices ?? []).find(
      (d) => String(d.id ?? "") === id
    );
    const suggested = fromDongle?.suggested_host ?? fromDiscover?.suggested_host;
    if (suggested) {
      setSshHost((prev) => (prev.trim() ? prev : String(suggested)));
    }
    void load("lan", id);
  };

  const conn = useMemo(
    () => connectionState(dongle, tab, loading, listSource, routes.length, emptyReason),
    [dongle, tab, loading, listSource, routes.length, emptyReason]
  );

  const metrics = latestMetrics(events, "ingest");
  const frac = progressOf(events, "ingest");
  const ingestActive = events.some(
    (e) => e.stage === "ingest" && (e.kind === "stage" || e.kind === "progress")
  );

  const discoveredDevices = dongle?.devices ?? [];
  const sshConfigured = Boolean(discover?.ssh?.configured || discover?.ssh?.host);
  const preferForIngest: RouteSource = tab === "lan" ? "ssh" : "connect";
  const lanAvailable = Boolean(
    dongle?.ssh_available ||
      dongle?.adb_available ||
      (dongle?.adb_status ?? "").toLowerCase() === "found" ||
      (dongle?.adb_status ?? "").toLowerCase() === "ready"
  );

  return (
    <div className={`ingest-pane${routes.length > 0 ? " has-routes" : ""}`}>
      <div className="ingest-head">
        <div className="ingest-dongle">
          <span className="k">source</span>
          <span className={`conn-chip tone-${conn.tone}`} title={conn.detail}>
            {conn.label}
          </span>
          <span className="source-chip" title="Resolved list source">
            {listSource}
            {tab === "public" ? " · public" : tab === "mine" ? " · mine" : ""}
          </span>
        </div>
      </div>

      <p className="ingest-conn-detail muted">{conn.detail}</p>

      {/* One calm segmented picker */}
      <div className="ingest-source-tabs" role="tablist" aria-label="Route source">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "public"}
          className={tab === "public" ? "active" : ""}
          disabled={loading}
          onClick={() => void load("public")}
          title="GET /routes?source=connect&scope=public"
        >
          Public routes
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "mine"}
          className={tab === "mine" ? "active" : ""}
          disabled={loading}
          onClick={() => void load("mine")}
          title="GET /routes?source=connect&scope=mine"
        >
          My Connect
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "lan"}
          className={tab === "lan" ? "active" : ""}
          disabled={loading}
          onClick={() => void load("lan")}
          title={
            lanAvailable || sshConfigured
              ? "GET /routes?source=ssh"
              : "SSH/ADB — configure under Connection if offline"
          }
        >
          SSH/ADB
        </button>
      </div>

      <div className="ingest-actions primary-row">
        <button
          className="primary"
          disabled={busy || loading || !selected}
          onClick={() => onIngest({ source: preferForIngest, routeId: selected })}
          title="Ingest the selected route"
        >
          Ingest selected
        </button>
        <button
          disabled={loading}
          onClick={() => void load(tab, pickedDevice)}
          title="Refresh route list"
        >
          Refresh
        </button>
      </div>

      {/* Connection disclosure — JWT / Dongle / SSH secondary */}
      <details
        className="ingest-conn-details"
        open={connOpen || emptyReason === "connect_not_configured" || emptyReason === "dongle_id_required"}
        onToggle={(e) => setConnOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary>Connection</summary>

        <div className="ingest-dongle-row" aria-label="Dongle ID">
          <input
            type="text"
            placeholder="Dongle ID (auto from ADB/SSH or type)"
            value={dongleDraft}
            onChange={(e) => {
              dongleTouchedRef.current = true;
              setDongleOrigin("manual");
              setDongleDraft(e.target.value);
            }}
            disabled={loading}
            aria-label="Dongle ID"
            className="mono"
          />
          <button
            disabled={loading || !dongleDraft.trim() || dongleDraft.trim().length < 8}
            onClick={() => void saveDongle()}
            title="POST /dongle — never saves demo 3e2de7ed…"
          >
            Save Dongle
          </button>
          {dongleOrigin === "adb" && (
            <span className="dongle-origin-chip" title="Read /data/params/d/DongleId via ADB">
              Auto from ADB
            </span>
          )}
          {dongleOrigin === "ssh" && (
            <span className="dongle-origin-chip" title="Read /data/params/d/DongleId via SSH">
              Auto from SSH
            </span>
          )}
          {dongleOrigin === "manual" && dongleDraft.trim() && (
            <span className="dongle-origin-chip muted" title="Typed / Save Dongle">
              Manual Save
            </span>
          )}
          {dongleOrigin === "saved" && dongle?.dongle_id && (
            <span className="dongle-origin-chip muted" title="Loaded from cache / env">
              Saved
            </span>
          )}
        </div>

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

        <div className="ingest-ssh-row" aria-label="SSH configuration">
          <div className="ingest-ssh-grid">
            <input
              type="text"
              placeholder="SSH host (mici LAN IP)"
              value={sshHost}
              onChange={(e) => setSshHost(e.target.value)}
              disabled={loading}
              aria-label="SSH host"
            />
            <input
              type="text"
              placeholder="user"
              value={sshUser}
              onChange={(e) => setSshUser(e.target.value)}
              disabled={loading}
              aria-label="SSH user"
            />
            <input
              type="text"
              inputMode="numeric"
              placeholder="port"
              value={sshPort}
              onChange={(e) => setSshPort(e.target.value)}
              disabled={loading}
              aria-label="SSH port"
              className="ingest-ssh-port"
            />
            <input
              type="text"
              placeholder="identity path (optional)"
              value={sshIdentity}
              onChange={(e) => setSshIdentity(e.target.value)}
              disabled={loading}
              aria-label="SSH identity path"
            />
          </div>
          <div className="ingest-ssh-actions">
            <button
              disabled={loading || !sshHost.trim()}
              onClick={() => void saveSsh()}
              title="POST /discover/ssh"
            >
              Save SSH
            </button>
            <button
              disabled={loading || !sshHost.trim()}
              onClick={() => void testSsh()}
              title="POST /discover/ssh/test"
            >
              Test
            </button>
          </div>
          {sshProbeNote && <div className="ingest-note">{sshProbeNote}</div>}
        </div>
      </details>

      {discoveredDevices.length > 0 && tab === "lan" && (
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
                  title={`Select discovered ${kind}`}
                  onClick={() => pickDevice(id)}
                >
                  <span className="device-pick-name">{String(dev.name ?? dev.id ?? "device")}</span>
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

      {/* Routes are the hero */}
      <div className="route-list" role="listbox" aria-label="routes">
        {loading && (
          <EmptyState
            title={
              tab === "lan"
                ? "Scanning LAN…"
                : tab === "public"
                  ? "Loading public routes"
                  : "Loading My Connect"
            }
            body={
              tab === "lan"
                ? "Looking for mici over ADB and SSH."
                : tab === "public"
                  ? "Shared & public drives from Connect — no local dongle required."
                  : "Asking comma Connect for routes on your saved dongle."
            }
          />
        )}
        {!loading && !listError && routes.length === 0 && tab === "public" && (
          <EmptyState
            title={
              emptyReason === "connect_not_configured" || emptyReason === "connect_unauthorized"
                ? "Needs JWT"
                : "No public routes"
            }
            body={
              routesMessage ||
              (emptyReason === "connect_not_configured" || emptyReason === "connect_unauthorized"
                ? "Paste Connect JWT under Connection — honest empty until then."
                : "No shared/public Connect hits for this account.")
            }
            hint="GET /routes?source=connect&scope=public"
          />
        )}
        {!loading && !listError && routes.length === 0 && tab === "mine" && (
          <EmptyState
            title={
              emptyReason === "dongle_id_required"
                ? "Needs Dongle"
                : dongle?.connect_available
                  ? "No Connect routes"
                  : "Needs JWT"
            }
            body={
              routesMessage ||
              (emptyReason === "dongle_id_required"
                ? "Save Dongle under Connection, or use Public / SSH/ADB."
                : dongle?.connect_available
                  ? "Connect is up, but no routes for this dongle."
                  : "Paste Connect JWT under Connection.")
            }
            hint="GET /routes?source=connect&scope=mine"
          />
        )}
        {!loading && !listError && routes.length === 0 && tab === "lan" && (
          <EmptyState
            title={
              listSource === "ssh" || sshConfigured || dongle?.ssh_available
                ? "SSH · 0 routes"
                : "Nothing on LAN yet"
            }
            body={
              routesMessage ||
              (listSource === "ssh" || sshConfigured || dongle?.ssh_available
                ? "SSH ok · 0 routes under /data/media/0/realdata"
                : "No ADB or SSH routes found — open Connection.")
            }
            hint={emptyReason ? `empty_reason=${emptyReason}` : "GET /routes?source=ssh"}
            actions={
              <>
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => void load("lan", pickedDevice)}
                >
                  Refresh
                </button>
                <button type="button" disabled={loading} onClick={() => void testSsh()}>
                  Verify path
                </button>
              </>
            }
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
            const scopeLabel =
              r.meta?.scope === "shared"
                ? "shared"
                : r.meta?.scope === "public" || r.meta?.is_public
                  ? "public"
                  : null;
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
                  {scopeLabel && (
                    <span className="badge badge-scope" title={`${scopeLabel} Connect drive`}>
                      {scopeLabel}
                    </span>
                  )}
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
