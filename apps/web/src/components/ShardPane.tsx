import type { DistilleryEvent, StageName, StageStatus } from "../types/events";
import { EmptyState } from "./EmptyState";

function latestMetrics(
  events: DistilleryEvent[],
  stage?: StageName
): [string, { value: number; unit?: string }][] {
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

function progressOf(events: DistilleryEvent[], stage: StageName): {
  fraction: number;
  detail?: string;
} {
  let fraction = 0;
  let detail: string | undefined;
  for (const ev of events) {
    if (ev.kind === "progress" && ev.stage === stage) {
      fraction = Number(ev.payload.fraction ?? 0);
      const d = ev.payload.detail;
      detail = typeof d === "string" && d.length > 0 ? d : undefined;
    }
  }
  return { fraction, detail };
}

function latestStageStatus(
  events: DistilleryEvent[],
  stage: StageName
): { status: StageStatus; detail?: string } | null {
  let hit: { status: StageStatus; detail?: string } | null = null;
  for (const ev of events) {
    if (ev.kind !== "stage" || ev.stage !== stage) continue;
    const status = String(ev.payload.status ?? "") as StageStatus;
    if (!status) continue;
    const d = ev.payload.detail;
    hit = {
      status,
      detail: typeof d === "string" && d.length > 0 ? d : undefined,
    };
  }
  return hit;
}

function latestShardDecision(events: DistilleryEvent[]): {
  title: string;
  chosen?: string;
} | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]!;
    if (ev.kind !== "decision" || ev.stage !== "shard") continue;
    return {
      title: String(ev.payload.title ?? "Decision"),
      chosen:
        typeof ev.payload.chosen === "string" ? ev.payload.chosen : undefined,
    };
  }
  return null;
}

function pct(frac: number): string {
  return `${Math.round(Math.min(1, Math.max(0, frac)) * 100)}%`;
}

/**
 * Shard pack pane — binds to stage=shard progress / metric / stage events
 * the same way Ingest/Train panes do. Idle copy stays honest until Craig's
 * pack contracts stream real events (demo already emits them on Run demo).
 */
export function ShardPane({ events }: { events: DistilleryEvent[] }) {
  const metrics = latestMetrics(events, "shard");
  const { fraction, detail } = progressOf(events, "shard");
  const stage = latestStageStatus(events, "shard");
  const decision = latestShardDecision(events);

  const hasShardSignal =
    Boolean(stage) ||
    metrics.length > 0 ||
    events.some(
      (e) =>
        e.stage === "shard" &&
        (e.kind === "progress" || e.kind === "log" || e.kind === "decision")
    );

  const ingestDone = events.some(
    (e) =>
      e.kind === "stage" &&
      e.stage === "ingest" &&
      e.payload.status === "done"
  );
  const ingestRunning = events.some(
    (e) =>
      e.kind === "stage" &&
      e.stage === "ingest" &&
      e.payload.status === "running"
  );

  if (!hasShardSignal) {
    if (ingestRunning) {
      return (
        <EmptyState
          title="Shard packing idle"
          body="Waiting for ingest to finish. Segments pack into training shards only after stage=shard events arrive."
          hint="No pack progress invented while idle."
        />
      );
    }
    if (ingestDone) {
      return (
        <EmptyState
          title="Waiting to pack"
          body="Ingest is done. This pane stays quiet until the pipeline emits shard stage, progress, or metric events."
          hint="Run demo streams pack events · dedicated shard jobs land with Craig."
        />
      );
    }
    return (
      <EmptyState
        title="Shard packing idle"
        body="Frame windows and labels become training shards here. Nothing is packing until shard events stream on the bus."
        hint="stage=shard · progress / metric / stage"
      />
    );
  }

  const status = stage?.status ?? (fraction >= 1 ? "done" : "running");
  const statusLabel =
    status === "done"
      ? "packed"
      : status === "failed"
        ? "failed"
        : status === "running"
          ? "packing"
          : status;
  const headline =
    stage?.detail ??
    (status === "done"
      ? "Training shards ready"
      : status === "failed"
        ? "Shard packing failed"
        : "Packing training shards");
  const showBar = status === "running" || status === "done" || fraction > 0;
  const barWidth = status === "done" ? 1 : fraction;

  return (
    <div className="shard-pane">
      <div className="shard-head">
        <div className="shard-title-row">
          <span className="shard-headline">{headline}</span>
          <span className={`shard-status ${status}`}>{statusLabel}</span>
        </div>
        {decision?.chosen ? (
          <div className="shard-decision muted">
            <span className="k">{decision.title}</span>
            <span className="v mono">{decision.chosen}</span>
          </div>
        ) : (
          <div className="muted">Frame windows · labels · soft-target placeholders</div>
        )}
      </div>

      {showBar && (
        <div className="shard-progress">
          <div className="bar-track" aria-hidden>
            <div className="bar-fill" style={{ width: `${barWidth * 100}%` }} />
          </div>
          <div className="shard-progress-meta">
            <span className="mono">{pct(barWidth)}</span>
            <span className="muted">
              {detail ??
                (status === "done"
                  ? "done"
                  : status === "running"
                    ? "packing…"
                    : "—")}
            </span>
          </div>
        </div>
      )}

      {metrics.length > 0 ? (
        <div className="shard-metrics">
          {metrics.map(([k, { value, unit }]) => (
            <div key={k} className="metric-row">
              <span className="k">{k}</span>
              <span className="v">
                {Number.isFinite(value) && !Number.isInteger(value)
                  ? value.toFixed(2)
                  : value}
                {unit ? ` ${unit}` : ""}
              </span>
            </div>
          ))}
        </div>
      ) : status === "running" ? (
        <div className="muted">Awaiting shard metrics…</div>
      ) : null}
    </div>
  );
}
