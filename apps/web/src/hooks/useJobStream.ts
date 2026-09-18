import { useCallback, useEffect, useRef, useState } from "react";
import type { DistilleryEvent, StageName, StageStatus } from "../types/events";
import { STAGES } from "../types/events";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export interface JobState {
  jobId: string | null;
  status: string;
  events: DistilleryEvent[];
  stageStatus: Record<StageName, StageStatus>;
  connected: boolean;
  error: string | null;
}

const initialStages = (): Record<StageName, StageStatus> =>
  Object.fromEntries(STAGES.map((s) => [s, "pending"])) as Record<
    StageName,
    StageStatus
  >;

export function useJobStream() {
  const [state, setState] = useState<JobState>({
    jobId: null,
    status: "idle",
    events: [],
    stageStatus: initialStages(),
    connected: false,
    error: null,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const seen = useRef<Set<string>>(new Set());

  const applyEvent = useCallback((ev: DistilleryEvent) => {
    if (seen.current.has(ev.id)) return;
    seen.current.add(ev.id);
    setState((prev) => {
      const stageStatus = { ...prev.stageStatus };
      if (ev.kind === "stage" && ev.stage) {
        const st = (ev.payload.status as StageStatus) || "running";
        stageStatus[ev.stage] = st;
      }
      let status = prev.status;
      if (ev.kind === "stage" && ev.payload.status === "gated") status = "gated";
      if (ev.kind === "stage" && ev.stage === "flash" && (ev.payload.status === "done" || ev.payload.status === "skipped")) {
        status = "done";
      }
      if (ev.kind === "stage" && ev.payload.status === "running" && status === "pending") {
        status = "running";
      }
      return {
        ...prev,
        events: [...prev.events, ev],
        stageStatus,
        status,
      };
    });
  }, []);

  const connectWs = useCallback(
    (jobId: string) => {
      wsRef.current?.close();
      const url = API_BASE.replace(/^http/, "ws") + `/ws/jobs/${jobId}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => setState((p) => ({ ...p, connected: true, error: null }));
      ws.onclose = () => setState((p) => ({ ...p, connected: false }));
      ws.onerror = () =>
        setState((p) => ({ ...p, error: "WebSocket error", connected: false }));
      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data.error) {
            setState((p) => ({ ...p, error: data.error }));
            return;
          }
          applyEvent(data as DistilleryEvent);
        } catch {
          /* ignore */
        }
      };
    },
    [applyEvent]
  );

  const startDemo = useCallback(async () => {
    seen.current = new Set();
    setState({
      jobId: null,
      status: "pending",
      events: [],
      stageStatus: initialStages(),
      connected: false,
      error: null,
    });
    try {
      const res = await fetch(`${API_BASE}/jobs/demo`, { method: "POST" });
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setState((p) => ({ ...p, jobId: data.id, status: data.status || "pending" }));
      connectWs(data.id);
    } catch (e) {
      setState((p) => ({
        ...p,
        error: e instanceof Error ? e.message : "Failed to start demo",
        status: "idle",
      }));
    }
  }, [connectWs]);

  const confirmFlash = useCallback(async () => {
    const jobId = state.jobId;
    if (!jobId) return;
    // Prefer WS message; also hit REST
    try {
      wsRef.current?.send(JSON.stringify({ type: "flash_confirm" }));
    } catch {
      /* */
    }
    await fetch(`${API_BASE}/jobs/${jobId}/flash/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
  }, [state.jobId]);

  useEffect(() => {
    return () => wsRef.current?.close();
  }, []);

  return { ...state, startDemo, confirmFlash, apiBase: API_BASE };
}
