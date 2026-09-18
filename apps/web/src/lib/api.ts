/** Thin HTTP helpers for Craig’s M1 ingest contracts. */

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export type RouteSource = "auto" | "connect" | "ssh" | "fixture";

export interface RouteSummary {
  route_id: string;
  dongle_id: string;
  display_name: string;
  source: string;
  start_time?: string | null;
  end_time?: string | null;
  length_s?: number | null;
  segment_count?: number;
  meta?: Record<string, unknown>;
}

export interface RoutesResponse {
  dongle_id: string;
  source: string;
  device?: string | null;
  ssh_host?: string | null;
  routes: RouteSummary[];
  /** Honest empty/error copy when source=ssh|connect and no silent fixture swap. */
  message?: string | null;
  empty_reason?: string | null;
  error?: string | null;
}

/** Today’s /dongle + tolerant placeholders for Craig’s richer device discovery. */
export interface DongleInfo {
  dongle_id: string;
  cams: string[];
  connect_available: boolean;
  ssh_available: boolean;
  force_fixture: boolean;
  /** Future: discovered devices on LAN / Connect. */
  devices?: Array<{
    id?: string;
    name?: string;
    kind?: string;
    online?: boolean;
    [key: string]: unknown;
  }>;
  /** Future: connect_status — "connected" | "needs_jwt" | "offline" | … */
  connect_status?: string | null;
  /** Future: lan_scan result summary (SSH + ADB). */
  lan_scan?: {
    status?: string;
    found?: number;
    scanning?: boolean;
    [key: string]: unknown;
  } | null;
  /** Future: ADB-over-LAN discovery available. */
  adb_available?: boolean;
  /** Future: adb_status — "found" | "scanning" | "missing" | … */
  adb_status?: string | null;
  configured?: boolean;
  /** Real DongleId from device params (ADB/SSH) — never invented. */
  suggested_dongle_id?: string | null;
  /** Primary: adb | ssh when suggested_dongle_id was read from the device. */
  discovered_from?: "adb" | "ssh" | string | null;
  /** Alias of discovered_from. */
  dongle_discovery_source?: "adb" | "ssh" | string | null;
  dongle_discovery_serial?: string | null;
  dongle_discovery_error?: string | null;
}

/** Nested train device from GET /health and GET /status/runtime. */
export interface DeviceInfo {
  found?: boolean;
  ready?: boolean;
  kind?: string | null;
  name?: string | null;
  backend?: string | null;
  error?: string | null;
  detail?: string | null;
  [key: string]: unknown;
}

/**
 * GET /health + /status/runtime — tinygrad + device {found,ready,kind,name,backend}.
 */
export interface HealthResponse {
  ok?: boolean;
  status?: string;
  service?: string;
  mode?: string | null;
  ml_backends?: Record<string, string>;
  tinygrad?: string | null;
  tinygrad_status?: string | null;
  /** Nested device object (live Craig shape) or legacy string. */
  device?: DeviceInfo | string | null;
  device_status?: string | null;
  device_name?: string | null;
  train_device?: string | null;
  gpu?: string | null;
  gpu_status?: string | null;
  gpu_name?: string | null;
  driving_hours?: number | null;
  route_hours?: number | null;
  total_hours?: number | null;
  hours?: number | null;
  hours_known?: boolean;
  hours_info?: {
    hours?: number;
    known?: boolean;
    min_hours?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface DiscoverDevice {
  id?: string;
  model?: string | null;
  state?: string;
  transport?: string;
  suggested_host?: string | null;
  name?: string;
  kind?: string;
  online?: boolean;
  [key: string]: unknown;
}

export interface DiscoverOverview {
  dongle_id?: string;
  suggested_dongle_id?: string | null;
  discovered_from?: "adb" | "ssh" | string | null;
  dongle_discovery_source?: "adb" | "ssh" | string | null;
  dongle_discovery_serial?: string | null;
  dongle_discovery_error?: string | null;
  cams?: string[];
  devices?: {
    ok?: boolean;
    adb_available?: boolean;
    error?: string | null;
    devices?: DiscoverDevice[];
  };
  connect?: {
    configured?: boolean;
    available?: boolean;
    jwt_masked?: string | null;
    jwt_source?: string | null;
    dongle_id?: string;
    [key: string]: unknown;
  };
  ssh?: {
    configured?: boolean;
    available?: boolean;
    host?: string | null;
    user?: string | null;
    port?: number | null;
    identity_path?: string | null;
    key_set?: boolean;
    cache_path?: string | null;
    source?: string | null;
    [key: string]: unknown;
  };
  fixture?: {
    available?: boolean;
    label?: string;
    offline_fallback?: boolean;
    forced?: boolean;
  };
  sources?: Record<string, boolean>;
  [key: string]: unknown;
}

export interface ReadyGap {
  code: string;
  message: string;
}

export interface ReadyResponse {
  ok: boolean;
  ready?: boolean;
  gaps: ReadyGap[];
  hours?: Record<string, unknown> | null;
  hours_gate?: Record<string, unknown> | null;
  device?: Record<string, unknown> | null;
  teacher?: Record<string, unknown> | null;
  min_train_hours?: number;
  allow_toy?: boolean;
  force_fixture?: boolean;
  probe?: Record<string, unknown> | null;
  live?: boolean;
  licensed?: boolean;
  [key: string]: unknown;
}

export class TrainAllNotReadyError extends Error {
  gaps: ReadyGap[];
  status: number;
  constructor(gaps: ReadyGap[], status = 409) {
    super("train_all not ready");
    this.name = "TrainAllNotReadyError";
    this.gaps = gaps;
    this.status = status;
  }
}


/**
 * Selected / available teacher models.
 * Live path: commaai/openpilot master big driving model (Graig/Craig fetch/list).
 * Never Chestnut. Fixture must be labeled.
 */
export interface TeacherModel {
  id?: string;
  name?: string;
  version?: string;
  /** e.g. "comma_master" | "fixture" | "cinque" */
  source?: string;
  label?: string;
  live?: boolean;
  fixture?: boolean;
  [key: string]: unknown;
}

export const BIG_TEACHER_NAME = "big_driving_supercombo";

function isBigTeacher(model: TeacherModel | null | undefined): boolean {
  return [model?.name, model?.id, model?.label]
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim().replace(/\.onnx$/i, ""))
    .includes(BIG_TEACHER_NAME);
}

export interface TeacherInfo {
  selected?: TeacherModel | null;
  /** Future: list from GET /teachers or /health.teachers */
  teachers?: TeacherModel[];
  /** "live" | "fixture" | "unknown" */
  status?: string | null;
  source?: string | null;
  model_name?: string | null;
  model_version?: string | null;
  live?: boolean;
  fixture?: boolean;
  label?: string | null;
  teacher_artifact?: TeacherArtifact | null;
  [key: string]: unknown;
}

export interface JobSummary {
  id: string;
  kind: string;
  status: string;
  created_at: string;
  event_count: number;
  route_id?: string | null;
}

export function apiBase(): string {
  return API_BASE;
}

export function wsUrl(jobId: string): string {
  return API_BASE.replace(/^http/, "ws") + `/ws/jobs/${jobId}`;
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      /* */
    }
    const err = new Error(`API ${res.status}`) as Error & {
      status?: number;
      detail?: unknown;
    };
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return res.json() as Promise<T>;
}

export function fetchDongle(): Promise<DongleInfo> {
  return jsonFetch("/dongle");
}

/** Persist dongle id (env + .cache/dongle_id) — mirrors Save JWT. */
export function saveDongleId(dongleId: string, persist = true): Promise<DongleInfo> {
  return jsonFetch("/dongle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dongle_id: dongleId, persist }),
  });
}

/** Alias under /discover/dongle (same payload). */
export function postDiscoverDongle(dongleId: string, persist = true): Promise<DongleInfo> {
  return jsonFetch("/discover/dongle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dongle_id: dongleId, persist }),
  });
}

export function fetchHealth(): Promise<HealthResponse> {
  return jsonFetch("/health");
}

export function fetchRuntimeStatus(): Promise<HealthResponse> {
  return jsonFetch("/status/runtime");
}

/** Prefer /status/runtime; fall back to /health. */
export async function fetchStatusChipsSource(): Promise<HealthResponse> {
  try {
    return await fetchRuntimeStatus();
  } catch {
    return fetchHealth();
  }
}

export function fetchDiscover(): Promise<DiscoverOverview> {
  return jsonFetch("/discover");
}

export function fetchDiscoverDevices(): Promise<{
  ok?: boolean;
  adb_available?: boolean;
  error?: string | null;
  devices: DiscoverDevice[];
}> {
  return jsonFetch("/discover/devices");
}

export function fetchDiscoverConnect(): Promise<DiscoverOverview["connect"]> {
  return jsonFetch("/discover/connect");
}

export function postDiscoverConnect(jwt: string, persist = true): Promise<DiscoverOverview["connect"]> {
  return jsonFetch("/discover/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jwt, persist }),
  });
}

/** Alias matching Connect JWT naming in Expo panes. */
export const saveConnectJwt = postDiscoverConnect;

export type DiscoverSshStatus = NonNullable<DiscoverOverview["ssh"]> & {
  probe?: { ok: boolean; error?: string | null };
  persisted?: boolean;
};

export type SshConfigPayload = {
  host: string;
  user?: string;
  port?: number;
  identity_path?: string | null;
  persist?: boolean;
  test?: boolean;
};

export function fetchDiscoverSsh(): Promise<DiscoverSshStatus> {
  return jsonFetch("/discover/ssh");
}

export function saveDiscoverSsh(payload: SshConfigPayload): Promise<DiscoverSshStatus> {
  return jsonFetch("/discover/ssh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      host: payload.host,
      user: payload.user ?? "comma",
      port: payload.port ?? 22,
      identity_path: payload.identity_path ?? null,
      persist: payload.persist ?? true,
      test: payload.test ?? false,
    }),
  });
}

export function testDiscoverSsh(): Promise<{ ok: boolean; error?: string | null }> {
  return jsonFetch("/discover/ssh/test", { method: "POST" });
}

export function fetchReady(opts?: {
  teacher?: string | null;
  allow_toy?: boolean;
  force_fixture?: boolean;
}): Promise<ReadyResponse> {
  const q = new URLSearchParams();
  if (opts?.teacher) q.set("teacher", opts.teacher);
  if (opts?.allow_toy) q.set("allow_toy", "true");
  if (opts?.force_fixture) q.set("force_fixture", "true");
  const qs = q.toString();
  return jsonFetch(`/ready${qs ? `?${qs}` : ""}`);
}

export interface TeacherArtifact {
  name?: string;
  ok?: boolean;
  live?: boolean;
  cached?: boolean;
  path?: string | null;
  sha256?: string | null;
  source?: string | null;
  label?: string | null;
  detail?: string | null;
  error?: string | null;
  bytes?: number;
  [key: string]: unknown;
}

/** POST /teachers/pull start response (Craig #24 / docs/teachers-pull-contract.json). */
export interface TeacherPullJobStart {
  id: string;
  kind: string;
  status: string;
  created_at?: string;
  teacher?: string;
  default_teacher?: string;
  label?: string | null;
  live?: boolean;
  cached?: boolean;
  ok?: boolean | null;
  teacher_artifact?: TeacherArtifact | null;
  ws?: string;
  events_url?: string;
}

export interface TeacherPullResult extends TeacherInfo {
  ok?: boolean;
  label?: string | null;
  teacher_artifact?: TeacherArtifact | null;
  progress?: { fraction: number; detail?: string };
  error?: string | null;
  jobId?: string;
}

export type TeacherPullProgressCb = (update: {
  fraction: number;
  detail?: string;
  event?: Record<string, unknown>;
}) => void;

function normalizeTeachersPayload(raw: {
  teachers?: TeacherModel[];
  selected?: TeacherModel | null;
  source?: string | null;
  label?: string | null;
  teacher_artifact?: TeacherArtifact | null;
  count?: number;
}): TeacherInfo {
  const rawList = raw.teachers ?? [];
  const list = rawList.filter(isBigTeacher);
  // Prefer verified cache artifact over catalog listing (listing may be fixture when GitHub is down).
  const artifact = raw.teacher_artifact ?? null;
  const artifactLive = artifact?.live === true;
  // Prefer label from GET /teachers when Craig sets comma master · / fixture ·
  const apiLabel = typeof raw.label === "string" ? raw.label : null;
  // The API may still select the old stock model; never let that selection
  // leak into Teach. Prefer a big entry from the filtered catalog instead.
  let selected = isBigTeacher(raw.selected) ? raw.selected : list[0] ?? null;
  if (artifactLive && selected) {
    selected = {
      ...selected,
      live: true,
      fixture: false,
      source: String(artifact?.source ?? "comma_master"),
      label: String(artifact?.label ?? apiLabel ?? `comma master · ${BIG_TEACHER_NAME}`),
    };
  } else if (apiLabel?.startsWith("comma master") && selected) {
    selected = {
      ...selected,
      live: true,
      fixture: false,
      source: "comma_master",
      label: apiLabel,
    };
  }
  const src = String(
    artifactLive || apiLabel?.startsWith("comma master")
      ? artifact?.source ?? "comma_master"
      : raw.source ?? selected?.source ?? ""
  );
  const live =
    artifactLive ||
    apiLabel?.startsWith("comma master") === true ||
    selected?.live === true ||
    src.includes("openpilot") ||
    src === "comma_master";
  const fixture =
    !live &&
    (apiLabel?.startsWith("fixture") === true ||
      src === "fixture" ||
      selected?.source === "fixture" ||
      selected?.live === false ||
      artifact?.live === false);
  return {
    selected,
    teachers: list,
    status: fixture ? "fixture" : live ? "live" : "unknown",
    source: fixture ? "fixture" : live ? "comma_master" : raw.source ?? null,
    model_name: selected?.name ?? BIG_TEACHER_NAME,
    model_version: selected?.version ?? null,
    live,
    fixture,
    label: apiLabel ?? selected?.label ?? null,
    teacher_artifact: artifact,
  };
}

/**
 * GET /teachers — the Teach UI exposes only the locked big teacher.
 * Never invent a live comma-master claim from silence.
 * Prefer teacher_artifact when Craig cache is verified live.
 */
export async function fetchTeachers(): Promise<TeacherInfo> {
  const raw = await jsonFetch<{
    teachers?: TeacherModel[];
    selected?: TeacherModel | null;
    source?: string | null;
    label?: string | null;
    teacher_artifact?: TeacherArtifact | null;
    count?: number;
  }>("/teachers");
  return normalizeTeachersPayload(raw);
}

/**
 * POST /teachers/pull — start Craig teacher_pull job (big only).
 * Progress streams on /ws/jobs/{id}. Does not wait for completion.
 */
export function startTeacherPullJob(opts?: {
  force_download?: boolean;
  force_fixture?: boolean;
}): Promise<TeacherPullJobStart> {
  return jsonFetch<TeacherPullJobStart>("/teachers/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      force_download: opts?.force_download ?? false,
      force_fixture: opts?.force_fixture ?? false,
    }),
  });
}

/**
 * POST /teachers/pull + WS /ws/jobs/{id} until teach stage done/failed,
 * then refresh GET /teachers for the chip (docs/teachers-pull-contract.json).
 */
export async function pullLiveTeacher(
  opts?: {
    force_download?: boolean;
    force_fixture?: boolean;
    onProgress?: TeacherPullProgressCb;
    signal?: AbortSignal;
  }
): Promise<TeacherPullResult> {
  const start = await startTeacherPullJob({
    force_download: opts?.force_download,
    force_fixture: opts?.force_fixture,
  });
  const jobId = start.id;
  opts?.onProgress?.({
    fraction: 0.02,
    detail: start.label ?? `pulling · ${BIG_TEACHER_NAME}`,
  });

  let lastFrac = 0.02;
  let lastDetail = start.label ?? `pulling · ${BIG_TEACHER_NAME}`;
  let terminalLabel: string | null = null;
  let terminalLive: boolean | null = null;
  let terminalOk: boolean | null = null;
  let warnMsg: string | null = null;

  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const ws = new WebSocket(wsUrl(jobId));
    const fail = (err: Error) => {
      if (settled) return;
      settled = true;
      try {
        ws.close();
      } catch {
        /* */
      }
      reject(err);
    };
    const done = () => {
      if (settled) return;
      settled = true;
      try {
        ws.close();
      } catch {
        /* */
      }
      resolve();
    };

    const onAbort = () => fail(new Error("Pull aborted"));
    opts?.signal?.addEventListener("abort", onAbort);

    const timer = window.setTimeout(() => {
      fail(new Error("Teacher pull timed out"));
    }, 180_000);

    const cleanup = () => {
      window.clearTimeout(timer);
      opts?.signal?.removeEventListener("abort", onAbort);
    };

    ws.onerror = () => {
      cleanup();
      fail(new Error("WebSocket error during teacher pull"));
    };
    ws.onclose = () => {
      // If closed before stage done, try events poll fallback once
      if (!settled) {
        void (async () => {
          try {
            const events = await jsonFetch<
              Array<{
                kind?: string;
                stage?: string | null;
                payload?: Record<string, unknown>;
              }>
            >(`/jobs/${jobId}/events`);
            for (const ev of events) {
              if (ev.kind === "progress" && ev.stage === "teach") {
                lastFrac = Number(ev.payload?.fraction ?? lastFrac);
                lastDetail = String(ev.payload?.detail ?? lastDetail);
              }
              if (
                ev.kind === "stage" &&
                ev.stage === "teach" &&
                (ev.payload?.status === "done" || ev.payload?.status === "failed")
              ) {
                terminalLabel = String(ev.payload?.detail ?? ev.payload?.label ?? terminalLabel ?? "");
                if (typeof ev.payload?.live === "boolean") terminalLive = ev.payload.live;
                if (typeof ev.payload?.ok === "boolean") terminalOk = ev.payload.ok;
                cleanup();
                done();
                return;
              }
            }
            cleanup();
            fail(new Error("Teacher pull WS closed before done"));
          } catch (e) {
            cleanup();
            fail(e instanceof Error ? e : new Error("Teacher pull failed"));
          }
        })();
      }
    };
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(String(msg.data)) as {
          error?: string;
          kind?: string;
          stage?: string | null;
          payload?: Record<string, unknown>;
        };
        if (data.error) {
          cleanup();
          fail(new Error(data.error));
          return;
        }
        const kind = data.kind;
        const stage = data.stage;
        const payload = data.payload ?? {};
        if (kind === "progress" && stage === "teach") {
          lastFrac = Number(payload.fraction ?? lastFrac);
          lastDetail = String(payload.detail ?? lastDetail);
          opts?.onProgress?.({
            fraction: lastFrac,
            detail: lastDetail,
            event: data as Record<string, unknown>,
          });
        }
        if (kind === "warning" && stage === "teach") {
          warnMsg = String(payload.label ?? payload.code ?? "TEACHER_NOT_LIVE");
          if (typeof payload.label === "string") terminalLabel = payload.label;
        }
        if (kind === "decision" && stage === "teach") {
          if (typeof payload.chosen === "string") terminalLabel = payload.chosen;
          if (typeof payload.label === "string") terminalLabel = payload.label;
          if (typeof payload.live === "boolean") terminalLive = payload.live;
          if (typeof payload.ok === "boolean") terminalOk = payload.ok;
        }
        if (
          kind === "stage" &&
          stage === "teach" &&
          (payload.status === "done" || payload.status === "failed")
        ) {
          if (typeof payload.detail === "string") terminalLabel = payload.detail;
          if (typeof payload.label === "string") terminalLabel = payload.label;
          if (typeof payload.live === "boolean") terminalLive = payload.live;
          if (typeof payload.ok === "boolean") terminalOk = payload.ok;
          if (payload.status === "failed") {
            cleanup();
            fail(new Error(String(payload.detail ?? "Teacher pull failed")));
            return;
          }
          lastFrac = 1;
          opts?.onProgress?.({ fraction: 1, detail: lastDetail, event: data as Record<string, unknown> });
          cleanup();
          done();
        }
      } catch {
        /* ignore malformed */
      }
    };
  });

  // Contract: refresh chip from GET /teachers after done
  const info = await fetchTeachers();
  const live = info.live === true || terminalLive === true;
  const label =
    info.label ||
    terminalLabel ||
    (live
      ? `comma master · ${BIG_TEACHER_NAME}`
      : `fixture · ${BIG_TEACHER_NAME}`);
  return {
    ...info,
    live,
    fixture: !live,
    status: live ? "live" : "fixture",
    source: live ? "comma_master" : "fixture",
    label,
    ok: terminalOk ?? live,
    progress: { fraction: lastFrac, detail: lastDetail },
    error: live ? null : warnMsg || info.teacher_artifact?.error || info.teacher_artifact?.detail || null,
    jobId,
    teacher_artifact: info.teacher_artifact,
  };
}

/** Calm display: the big teacher only, or explicit offline fixture. */
export function formatTeacherLabel(info: TeacherInfo | null): {
  primary: string;
  tone: "live" | "fixture" | "unknown" | "checking";
  detail: string;
} {
  if (!info) {
    return {
      primary: "Teacher · unknown",
      tone: "unknown",
      detail: "No /teachers or /health teacher fields yet.",
    };
  }
  const selected = info.selected;
  const hasTeacherSignal = Boolean(selected || info.model_name || info.model_version);
  const isFixture =
    info.fixture === true ||
    info.status === "fixture" ||
    selected?.fixture === true ||
    selected?.source === "fixture" ||
    info.source === "fixture";
  const isLive =
    !isFixture &&
    (info.live === true ||
      info.status === "live" ||
      selected?.live === true ||
      info.source === "comma_master" ||
      selected?.source === "comma_master");

  if (isFixture) {
    return {
      primary: `fixture · ${BIG_TEACHER_NAME}`,
      tone: "fixture",
      detail: `Labeled fixture teacher · ${BIG_TEACHER_NAME} — offline, not commaai/openpilot master live.`,
    };
  }
  if (isLive) {
    return {
      primary: `comma master · ${BIG_TEACHER_NAME}`,
      tone: "live",
      detail: `commaai/openpilot master · ${BIG_TEACHER_NAME} — no Chestnut.`,
    };
  }
  return {
    primary: hasTeacherSignal ? `Teacher · ${BIG_TEACHER_NAME}` : "Teacher · unknown",
    tone: "unknown",
    detail: hasTeacherSignal
      ? `Teacher target locked to ${BIG_TEACHER_NAME}; list/source pending from Craig (/teachers).`
      : "Teacher list/source pending from Craig (/teachers).",
  };
}

export function fetchRoutes(
  source: RouteSource = "auto",
  limit = 20,
  opts?: { device?: string | null; ssh_host?: string | null }
): Promise<RoutesResponse> {
  const q = new URLSearchParams({ source, limit: String(limit) });
  if (opts?.device) q.set("device", opts.device);
  if (opts?.ssh_host) q.set("ssh_host", opts.ssh_host);
  return jsonFetch(`/routes?${q}`);
}

export function startIngestJob(body: {
  source?: RouteSource;
  route_id?: string | null;
}): Promise<JobSummary> {
  return jsonFetch("/jobs/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function startDemoJob(): Promise<JobSummary> {
  return jsonFetch("/jobs/demo", { method: "POST" });
}

export function startShardJob(body: {
  source?: RouteSource;
  route_id?: string | null;
}): Promise<JobSummary> {
  return jsonFetch("/jobs/shard", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function startTeachJob(body: {
  source?: RouteSource;
  route_id?: string | null;
}): Promise<JobSummary> {
  return jsonFetch("/jobs/teach", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function startTrainJob(body: {
  source?: RouteSource;
  route_id?: string | null;
}): Promise<JobSummary> {
  return jsonFetch("/jobs/train", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function startExportJob(body: {
  route_id?: string | null;
  checkpoint_path?: string | null;
} = {}): Promise<JobSummary> {
  return jsonFetch("/jobs/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function startEvalJob(body: {
  route_id?: string | null;
  onnx_path?: string | null;
  force_fail?: boolean;
  force_pass?: boolean;
} = {}): Promise<JobSummary> {
  return jsonFetch("/jobs/eval", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Simple-user ship path: teach→train→export→eval→gated flash. */
export function startPipelineJob(body: {
  source?: RouteSource;
  route_id?: string | null;
  include_flash?: boolean;
} = {}): Promise<JobSummary> {
  return jsonFetch("/jobs/pipeline", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: body.source ?? "fixture",
      route_id: body.route_id ?? null,
      include_flash: body.include_flash ?? true,
    }),
  });
}

/**
 * One-click train_all — never auto-flashes.
 * 409 → TrainAllNotReadyError with structured gaps from Craig.
 */
export async function startTrainAllJob(body: {
  source?: RouteSource;
  route_id?: string | null;
  teacher?: string | null;
  allow_toy?: boolean;
  force_fixture?: boolean;
} = {}): Promise<JobSummary> {
  const res = await fetch(`${API_BASE}/jobs/train_all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: body.source ?? "auto",
      route_id: body.route_id ?? null,
      teacher: body.teacher ?? null,
      allow_toy: body.allow_toy ?? false,
      force_fixture: body.force_fixture ?? false,
    }),
  });
  if (res.status === 409) {
    const detail = (await res.json().catch(() => ({}))) as {
      detail?: { gaps?: ReadyGap[]; message?: string } | ReadyGap[];
      gaps?: ReadyGap[];
    };
    const nested = detail.detail;
    const gaps = Array.isArray(nested)
      ? nested
      : nested && typeof nested === "object" && Array.isArray(nested.gaps)
        ? nested.gaps
        : Array.isArray(detail.gaps)
          ? detail.gaps
          : [];
    throw new TrainAllNotReadyError(gaps, 409);
  }
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<JobSummary>;
}

export function confirmFlashJob(jobId: string): Promise<{ ok: boolean }> {
  return jsonFetch(`/jobs/${jobId}/flash/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  });
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function formatRouteLength(lengthS: number | null | undefined): string {
  if (lengthS == null || !Number.isFinite(lengthS)) return "—";
  if (lengthS < 60) return `${Math.round(lengthS)}s`;
  if (lengthS < 3600) return `${(lengthS / 60).toFixed(1)} min`;
  return `${(lengthS / 3600).toFixed(2)} h`;
}

/** Derive calm chip labels from today’s /health (+ future fields). */
export type ChipTone = "ok" | "warn" | "off" | "checking" | "fixture";

export interface StatusChipModel {
  key: string;
  label: string;
  value: string;
  tone: ChipTone;
  title?: string;
}

function asStr(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v.trim();
  return null;
}

/**
 * Map /health → Device + tinygrad chips.
 * Never hard-code 7090-only readiness. Never imply live GPU teach when fixture.
 */
export function healthToStatusChips(health: HealthResponse | null, checking: boolean): StatusChipModel[] {
  if (checking && !health) {
    return [
      { key: "device", label: "Train device", value: "checking…", tone: "checking", title: "GET /health" },
      { key: "tinygrad", label: "tinygrad", value: "checking…", tone: "checking", title: "GET /health" },
    ];
  }

  const backends = health?.ml_backends ?? {};
  const teachBackend = asStr(backends.teach);
  const trainBackend = asStr(backends.train);
  const anyFixture =
    teachBackend === "fixture" ||
    trainBackend === "fixture" ||
    asStr(health?.tinygrad) === "fixture" ||
    asStr(health?.tinygrad_status) === "fixture" ||
    asStr(health?.mode) === "fixture";

  // --- tinygrad ---
  let tgValue = "unknown";
  let tgTone: ChipTone = "off";
  const tgRaw =
    asStr(health?.tinygrad_status) ??
    asStr(health?.tinygrad) ??
    null;

  if (tgRaw) {
    const low = tgRaw.toLowerCase();
    if (low === "ok" || low === "ready" || low === "present") {
      tgValue = "ok";
      tgTone = "ok";
    } else if (low === "missing" || low === "absent" || low === "error") {
      tgValue = "missing";
      tgTone = "warn";
    } else if (low === "fixture") {
      tgValue = "fixture";
      tgTone = "fixture";
    } else {
      tgValue = tgRaw;
      tgTone = "off";
    }
  } else if (teachBackend === "graig" || trainBackend === "graig") {
    // Live package path present — tinygrad presumed available for Expo
    tgValue = "ok";
    tgTone = "ok";
  } else if (anyFixture || teachBackend === "fixture" || trainBackend === "fixture") {
    tgValue = "fixture";
    tgTone = "fixture";
  } else if (!health) {
    tgValue = "unknown";
    tgTone = "off";
  }

  // --- Train device: prefer nested device {found,ready,kind,name,backend} ---
  const nested =
    health?.device && typeof health.device === "object"
      ? (health.device as DeviceInfo)
      : null;
  const deviceName =
    asStr(nested?.name) ??
    asStr(health?.device_name) ??
    asStr(health?.train_device) ??
    (typeof health?.device === "string" ? asStr(health.device) : null) ??
    asStr(health?.gpu_name) ??
    asStr(health?.gpu) ??
    null;
  const deviceKind = asStr(nested?.kind);
  const deviceReady = nested?.ready === true;
  const deviceFound = nested?.found === true;
  const modeFixture = asStr(health?.mode) === "fixture";

  let devValue = "unknown";
  let devTone: ChipTone = "off";
  let devTitle = "Train device — tinygrad-compatible (GPU or CPU). Not 7090-locked.";

  if (modeFixture || (anyFixture && !deviceFound && !deviceName)) {
    devValue = "fixture";
    devTone = "fixture";
    devTitle = "Fixture / offline mode — not a live train-device claim.";
  } else if (nested) {
    const kindBit = deviceKind ? `${deviceKind}` : null;
    const nameBit = deviceName;
    if (deviceReady) {
      const label = [nameBit, kindBit].filter(Boolean).join(" · ");
      devValue = label ? `${label} · ready` : "ready";
      devTone = "ok";
    } else if (deviceFound) {
      devValue = nameBit ? `${nameBit} · not ready` : "found · not ready";
      devTone = "warn";
    } else {
      devValue = "missing";
      devTone = "warn";
    }
    if (asStr(nested.backend)) {
      devTitle = `backend=${nested.backend}; kind=${deviceKind ?? "?"}`;
    }
  } else if (deviceName) {
    devValue = deviceName;
    devTone = "ok";
  } else if (!health) {
    devValue = "unknown";
    devTone = "off";
  } else {
    devValue = "unknown";
    devTone = "off";
  }

  return [
    {
      key: "device",
      label: "Train device",
      value: devValue,
      tone: devTone,
      title: devTitle,
    },
    {
      key: "tinygrad",
      label: "tinygrad",
      value: tgValue,
      tone: tgTone,
      title: "tinygrad runtime — ok / missing / fixture",
    },
  ];
}
