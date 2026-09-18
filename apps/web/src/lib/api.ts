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
  routes: RouteSummary[];
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
}

/**
 * GET /health — today: status, service, ml_backends.
 * Tolerant of Craig’s future train-device / tinygrad fields.
 */
export interface HealthResponse {
  status?: string;
  service?: string;
  /** Stage → "graig" | "fixture" (today). */
  ml_backends?: Record<string, string>;
  /** Future: tinygrad runtime — "ok" | "missing" | "fixture" | … */
  tinygrad?: string | null;
  tinygrad_status?: string | null;
  /** Future: train device discovery (GPU/CPU/whatever tinygrad sees). */
  device?: string | null;
  device_status?: string | null;
  device_name?: string | null;
  train_device?: string | null;
  gpu?: string | null;
  gpu_status?: string | null;
  gpu_name?: string | null;
  /** Future: driving-hours floor (≥50h). */
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
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<T>;
}

export function fetchDongle(): Promise<DongleInfo> {
  return jsonFetch("/dongle");
}


export function fetchHealth(): Promise<HealthResponse> {
  return jsonFetch("/health");
}

/**
 * Prefer GET /teachers when Craig lands it; fall back to /health teacher* fields.
 * Never invent a live comma-master claim from silence.
 */
export async function fetchTeachers(): Promise<TeacherInfo> {
  try {
    return await jsonFetch<TeacherInfo>("/teachers");
  } catch {
    const health = await fetchHealth();
    const extra = health as HealthResponse & {
      teacher?: TeacherInfo;
      teachers?: TeacherModel[];
    };
    const t = extra.teacher ?? null;
    const list = extra.teachers ?? t?.teachers ?? [];
    const backends = health.ml_backends ?? {};
    const teachBackend = typeof backends.teach === "string" ? backends.teach : null;
    const fixture =
      teachBackend === "fixture" ||
      t?.fixture === true ||
      t?.status === "fixture" ||
      list.some((m) => m.fixture || m.source === "fixture");
    const live =
      !fixture &&
      (t?.live === true ||
        teachBackend === "graig" ||
        t?.status === "live" ||
        list.some((m) => m.live));
    return {
      selected: t?.selected ?? list[0] ?? null,
      teachers: list,
      status: t?.status ?? (fixture ? "fixture" : live ? "live" : "unknown"),
      source: t?.source ?? (fixture ? "fixture" : live ? "comma_master" : null),
      model_name: t?.model_name ?? t?.selected?.name ?? null,
      model_version: t?.model_version ?? t?.selected?.version ?? null,
      live,
      fixture,
    };
  }
}

/** Calm display: "comma master · <model>" or explicit fixture. Never Chestnut. */
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
  const name =
    selected?.name ??
    info.model_name ??
    (typeof selected?.label === "string" ? selected.label : null);
  const version = selected?.version ?? info.model_version ?? null;
  const modelBit = [name, version].filter(Boolean).join(" ");
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
      primary: modelBit ? `fixture · ${modelBit}` : "fixture · offline teacher",
      tone: "fixture",
      detail: "Labeled fixture teacher — not commaai/openpilot master live.",
    };
  }
  if (isLive) {
    return {
      primary: modelBit
        ? `comma master · ${modelBit}`
        : "comma master · (model pending)",
      tone: "live",
      detail: "commaai/openpilot master big driving model — no Chestnut.",
    };
  }
  return {
    primary: modelBit ? `Teacher · ${modelBit}` : "Teacher · unknown",
    tone: "unknown",
    detail: "Teacher list/source pending from Craig (/teachers).",
  };
}

export function fetchRoutes(
  source: RouteSource = "auto",
  limit = 20
): Promise<RoutesResponse> {
  const q = new URLSearchParams({ source, limit: String(limit) });
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
    asStr(health?.tinygrad_status) === "fixture";

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

  // --- Train device (GPU if present, else CPU / whatever tinygrad sees) ---
  // Prefer explicit Craig fields; never claim 7090-only.
  const deviceName =
    asStr(health?.device_name) ??
    asStr(health?.train_device) ??
    asStr(health?.device) ??
    asStr(health?.gpu_name) ??
    asStr(health?.gpu) ??
    null;
  const deviceStatus =
    asStr(health?.device_status) ??
    asStr(health?.gpu_status) ??
    null;

  let devValue = "unknown";
  let devTone: ChipTone = "off";
  let devTitle = "Train device — tinygrad-compatible (GPU or CPU). Not 7090-locked.";

  if (anyFixture && !deviceStatus && !deviceName) {
    // Fixture path: never imply a live GPU/device is teaching
    devValue = "fixture";
    devTone = "fixture";
    devTitle = "Fixture backends active — not a live train-device claim.";
  } else if (deviceStatus || deviceName) {
    const statusLow = (deviceStatus ?? "").toLowerCase();
    const name = deviceName;
    if (statusLow === "ready" || statusLow === "found" || statusLow === "ok" || statusLow === "present") {
      devValue = name ? `${name} · ready` : "ready";
      devTone = "ok";
    } else if (statusLow === "missing" || statusLow === "absent" || statusLow === "none") {
      devValue = "missing";
      devTone = "warn";
    } else if (statusLow === "unknown" || statusLow === "checking") {
      devValue = statusLow === "checking" ? "checking…" : "unknown";
      devTone = statusLow === "checking" ? "checking" : "off";
    } else if (name) {
      // Name only — show it calmly as found, status unknown
      devValue = name;
      devTone = "ok";
      devTitle = `Device reported: ${name}. Status fields pending from /health.`;
    } else if (deviceStatus) {
      devValue = deviceStatus;
      devTone = "off";
    }
  } else if (teachBackend === "graig" || trainBackend === "graig") {
    // Packages live but no device field yet
    devValue = "unknown";
    devTone = "off";
    devTitle = "ML backends live; device discovery fields not on /health yet.";
  } else if (!health) {
    devValue = "unknown";
    devTone = "off";
  } else {
    devValue = "unknown";
    devTone = "off";
    devTitle = "No device_* fields on /health yet — Craig to add.";
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
