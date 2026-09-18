import type { DistilleryEvent } from "../types/events";
import {
  hasStageSignal,
  latestDecision,
  latestMetrics,
  latestStageStatus,
  progressOf,
  pct,
  stageDone,
  stageRunning,
} from "../lib/eventSelectors";
import { EmptyState } from "./EmptyState";

/**
 * Teacher pane — binds to stage=teach progress / metric / stage / decision.
 * Honest idle: no invented live GPU. Demo already streams teach events on Run demo.
 * Future: Craig /jobs/teach can feed the same event kinds.
 */
export function TeacherPane({ events }: { events: DistilleryEvent[] }) {
  const metrics = latestMetrics(events, "teach");
  const { fraction, detail } = progressOf(events, "teach");
  const stage = latestStageStatus(events, "teach");
  const decision = latestDecision(events, "teach");
  const signal = hasStageSignal(events, "teach");

  const shardDone = stageDone(events, "shard");
  const shardRunning = stageRunning(events, "shard");

  if (!signal) {
    if (shardRunning) {
      return (
        <EmptyState
          title="Teacher standing by"
          body="Waiting for shard packing to finish. Soft-label pass starts only when teach events arrive on the bus."
          hint="No live 7090 XT invented while idle"
        />
      );
    }
    if (shardDone) {
      return (
        <EmptyState
          title="Waiting to teach"
          body="Shards are ready. This pane stays quiet until the pipeline emits teach stage, progress, or metric events."
          hint="Run demo streams teach · /jobs/teach later"
        />
      );
    }
    return (
      <EmptyState
        title="Teacher standing by"
        body="Cinque/supercombo soft-labels on the 7090 XT appear here when teach events stream. Expo is mission control — not a live GPU dashboard."
        hint="stage=teach · progress / metric / stage · no Chestnut"
      />
    );
  }

  const status = stage?.status ?? (fraction >= 1 ? "done" : "running");
  const statusLabel =
    status === "done"
      ? "done"
      : status === "failed"
        ? "failed"
        : status === "running"
          ? "teaching"
          : status;
  const headline =
    stage?.detail ??
    (status === "done"
      ? "Soft labels ready"
      : status === "failed"
        ? "Teacher pass failed"
        : "Teacher soft-label pass");
  const showBar = status === "running" || status === "done" || fraction > 0;
  const barWidth = status === "done" ? 1 : fraction;

  return (
    <div className="stage-pane teacher-pane">
      <div className="stage-head">
        <div className="stage-title-row">
          <span className="stage-headline">{headline}</span>
          <span className={`stage-status ${status}`}>{statusLabel}</span>
        </div>
        {decision?.chosen ? (
          <div className="stage-decision muted">
            <span className="k">{decision.title}</span>
            <span className="v mono">{decision.chosen}</span>
          </div>
        ) : (
          <div className="muted">Cinque/supercombo · 7090 XT · no Chestnut</div>
        )}
      </div>

      {showBar && (
        <div className="stage-progress">
          <div className="bar-track" aria-hidden>
            <div className="bar-fill" style={{ width: `${barWidth * 100}%` }} />
          </div>
          <div className="stage-progress-meta">
            <span className="mono">{pct(barWidth)}</span>
            <span className="muted">
              {detail ??
                (status === "done"
                  ? "done"
                  : status === "running"
                    ? "labeling…"
                    : "—")}
            </span>
          </div>
        </div>
      )}

      {metrics.length > 0 ? (
        <div className="stage-metrics">
          {metrics.map(([k, { value, unit }]) => (
            <div key={k} className="metric-row">
              <span className="k">{k}</span>
              <span className="v">
                {Number.isFinite(value) && !Number.isInteger(value)
                  ? value.toFixed(1)
                  : value}
                {unit ? ` ${unit}` : ""}
              </span>
            </div>
          ))}
        </div>
      ) : status === "running" ? (
        <div className="muted">Awaiting teacher metrics…</div>
      ) : null}
    </div>
  );
}
