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

export interface DongleInfo {
  dongle_id: string;
  cams: string[];
  connect_available: boolean;
  ssh_available: boolean;
  force_fixture: boolean;
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
