import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiBase,
  confirmFlashJob,
  startDemoJob,
  startIngestJob,
  startShardJob,
  startPipelineJob,
  wsUrl,
  type RouteSource,
} from "../lib/api";
import type { DistilleryEvent, StageName, StageStatus } from "../types/events";
import { STAGES } from "../types/events";

export interface StageTiming {
  status: StageStatus;
  /** ISO ts when stage first became running (or gated). */
  startedAt: string | null;
  /** ISO ts when stage reached a terminal status. */
  endedAt: string | null;
  /** Latest progress fraction 0–1 for this stage. */
  weight: number;
  detail?: string | null;
}

export interface JobState {
  jobId: string | null;
  jobKind: "demo" | "ingest" | "shard" | "pipeline" | "teach" | "train" | "export" | "eval" | null;
  status: string;
  events: DistilleryEvent[];
  stageStatus: Record<StageName, StageStatus>;
  stageTiming: Record<StageName, StageTiming>;
  connected: boolean;
  error: string | null;
}

const initialStages = (): Record<StageName, StageStatus> =>
  Object.fromEntries(STAGES.map((s) => [s, "pending"])) as Record<
    StageName,
    StageStatus
  >;

const initialTiming = (): Record<StageName, StageTiming> =>
  Object.fromEntries(
    STAGES.map((s) => [
      s,
      { status: "pending" as StageStatus, startedAt: null, endedAt: null, weight: 0 },
    ])
  ) as Record<StageName, StageTiming>;

function blankState(): JobState {
  return {
    jobId: null,
    jobKind: null,
    status: "idle",
    events: [],
    stageStatus: initialStages(),
    stageTiming: initialTiming(),
    connected: false,
    error: null,
  };
}

export function useJobStream() {
  const [state, setState] = useState<JobState>(blankState);
  const wsRef = useRef<WebSocket | null>(null);
  const seen = useRef<Set<string>>(new Set());
  const jobIdRef = useRef<string | null>(null);

  const applyEvent = useCallback((ev: DistilleryEvent) => {
    if (seen.current.has(ev.id)) return;
    seen.current.add(ev.id);
    setState((prev) => {
      const stageStatus = { ...prev.stageStatus };
      const stageTiming = { ...prev.stageTiming };

      if (ev.kind === "stage" && ev.stage) {
        const st = (ev.payload.status as StageStatus) || "running";
        const detail = (ev.payload.detail as string | undefined) ?? null;
        stageStatus[ev.stage] = st;
        const prevT = stageTiming[ev.stage];
        const next: StageTiming = {
          ...prevT,
          status: st,
          detail,
        };
        if (
          (st === "running" || st === "gated") &&
          !prevT.startedAt
        ) {
          next.startedAt = ev.ts;
        }
        if (
          st === "done" ||
          st === "failed" ||
          st === "skipped"
        ) {
          next.endedAt = ev.ts;
          if (st === "done" || st === "skipped") next.weight = 1;
        }
        stageTiming[ev.stage] = next;
      }

      if (ev.kind === "progress" && ev.stage) {
        const frac = Number(ev.payload.fraction ?? 0);
        const prevT = stageTiming[ev.stage];
        stageTiming[ev.stage] = {
          ...prevT,
          weight: Math.min(1, Math.max(0, frac)),
          detail: (ev.payload.detail as string | undefined) ?? prevT.detail,
        };
      }

      let status = prev.status;
      if (ev.kind === "stage" && ev.payload.status === "gated") status = "gated";
      if (
        ev.kind === "stage" &&
        ev.stage === "flash" &&
        (ev.payload.status === "done" || ev.payload.status === "skipped")
      ) {
        status = "done";
      }
      if (
        ev.kind === "stage" &&
        prev.jobKind === "ingest" &&
        ev.stage === "ingest" &&
        ev.payload.status === "done"
      ) {
        status = "done";
      }
      if (
        ev.kind === "stage" &&
        prev.jobKind === "shard" &&
        ev.stage === "shard" &&
        ev.payload.status === "done"
      ) {
        status = "done";
      }
      if (
        ev.kind === "stage" &&
        ev.payload.status === "running" &&
        (status === "pending" || status === "idle")
      ) {
        status = "running";
      }
      if (ev.kind === "stage" && ev.payload.status === "failed") {
        status = "failed";
      }

      return {
        ...prev,
        events: [...prev.events, ev],
        stageStatus,
        stageTiming,
        status,
      };
    });
  }, []);

  const connectWs = useCallback(
    (jobId: string) => {
      wsRef.current?.close();
      const ws = new WebSocket(wsUrl(jobId));
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

  const beginJob = useCallback(
    async (
      kind: "demo" | "ingest" | "shard" | "pipeline" | "teach" | "train" | "export" | "eval",
      starter: () => Promise<{ id: string; status?: string }>
    ) => {
      seen.current = new Set();
      jobIdRef.current = null;
      setState({
        ...blankState(),
        status: "pending",
        jobKind: kind,
      });
      try {
        const data = await starter();
        jobIdRef.current = data.id;
        setState((p) => ({
          ...p,
          jobId: data.id,
          jobKind: kind,
          status: data.status || "pending",
        }));
        connectWs(data.id);
      } catch (e) {
        setState((p) => ({
          ...p,
          error: e instanceof Error ? e.message : "Failed to start job",
          status: "idle",
          jobKind: null,
        }));
      }
    },
    [connectWs]
  );

  const startDemo = useCallback(async () => {
    await beginJob("demo", () => startDemoJob());
  }, [beginJob]);

  const startIngest = useCallback(
    async (opts?: { source?: RouteSource; routeId?: string | null }) => {
      await beginJob("ingest", () =>
        startIngestJob({
          source: opts?.source ?? "fixture",
          route_id: opts?.routeId ?? null,
        })
      );
    },
    [beginJob]
  );

  const startShard = useCallback(
    async (opts?: { source?: RouteSource; routeId?: string | null }) => {
      await beginJob("shard", () =>
        startShardJob({
          source: opts?.source ?? "fixture",
          route_id: opts?.routeId ?? null,
        })
      );
    },
    [beginJob]
  );

  const startPipeline = useCallback(
    async (opts?: { source?: RouteSource; routeId?: string | null }) => {
      await beginJob("pipeline", () =>
        startPipelineJob({
          source: opts?.source ?? "fixture",
          route_id: opts?.routeId ?? null,
          include_flash: true,
        })
      );
    },
    [beginJob]
  );

  const confirmFlash = useCallback(async () => {
    const jobId = jobIdRef.current ?? state.jobId;
    if (!jobId) return;
    try {
      wsRef.current?.send(JSON.stringify({ type: "flash_confirm" }));
    } catch {
      /* */
    }
    await confirmFlashJob(jobId);
  }, [state.jobId]);

  useEffect(() => {
    return () => wsRef.current?.close();
  }, []);

  return {
    ...state,
    startDemo,
    startIngest,
    startShard,
    startPipeline,
    confirmFlash,
    apiBase: apiBase(),
  };
}
