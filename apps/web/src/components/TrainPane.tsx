import type { DistilleryEvent } from "../types/events";
import {
  hasStageSignal,
  latestDecision,
  latestMetrics,
  latestStageStatus,
  metricSeries,
  progressOf,
  pct,
  stageDone,
  stageRunning,
} from "../lib/eventSelectors";
import { EmptyState } from "./EmptyState";

/**
 * Train pane — binds to stage=train progress / metric / stage / decision.
 * Loss curve from train_loss series when present. Idle stays calm — no invented steps.
 * Future: Craig /jobs/train can feed the same event kinds.
 */
export function TrainPane({ events }: { events: DistilleryEvent[] }) {
  const losses = metricSeries(events, "train", "train_loss");
  const metrics = latestMetrics(events, "train");
  const { fraction, detail } = progressOf(events, "train");
  const stage = latestStageStatus(events, "train");
  const decision = latestDecision(events, "train");
  const signal = hasStageSignal(events, "train");
  const max = Math.max(...losses, 0.01);

  const teachDone = stageDone(events, "teach");
  const teachRunning = stageRunning(events, "teach");

  if (!signal) {
    if (teachRunning) {
      return (
        <EmptyState
          title="Student train idle"
          body="Waiting for the teacher pass to finish. Loss curves appear only when train events stream."
          hint="No invented steps while idle"
        />
      );
    }
    if (teachDone) {
      return (
        <EmptyState
          title="Waiting to train"
          body="Soft labels are ready. This pane stays quiet until the pipeline emits train stage, progress, or metric events."
          hint="Run demo streams train · /jobs/train later"
        />
      );
    }
    return (
      <EmptyState
        title="Student train idle"
        body="stock-modelV2 I/O student distill appears here when train events stream. Expo is workstation mission control — not a live trainer UI."
        hint="stage=train · progress / metric / stage"
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
          ? "training"
          : status;
  const headline =
    stage?.detail ??
    (status === "done"
      ? "Student distill complete"
      : status === "failed"
        ? "Train failed"
        : "Distill → stock-modelV2 I/O");
  const showBar = status === "running" || status === "done" || fraction > 0;
  const barWidth = status === "done" ? 1 : fraction;

  const sideMetrics = metrics.filter(([k]) => k !== "train_loss");

  return (
    <div className="stage-pane train-pane">
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
          <div className="muted">stock-modelV2 I/O student · tinygrad</div>
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
                    ? "training…"
                    : "—")}
            </span>
          </div>
        </div>
      )}

      {losses.length > 0 && (
        <div className="loss-chart" aria-label="train_loss series">
          {losses.map((v, i) => (
            <div
              key={i}
              className="loss-bar"
              style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
              title={String(v)}
            />
          ))}
        </div>
      )}

      {losses.length > 0 && (
        <div className="metric-row">
          <span className="k">train_loss</span>
          <span className="v">{losses[losses.length - 1]?.toFixed(4)}</span>
        </div>
      )}

      {sideMetrics.length > 0 && (
        <div className="stage-metrics">
          {sideMetrics.map(([k, { value, unit }]) => (
            <div key={k} className="metric-row">
              <span className="k">{k}</span>
              <span className="v">
                {Number.isFinite(value) && Math.abs(value) < 1 && value !== 0
                  ? value.toExponential(2)
                  : Number.isFinite(value) && !Number.isInteger(value)
                    ? value.toFixed(4)
                    : value}
                {unit ? ` ${unit}` : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {losses.length === 0 && status === "running" && (
        <div className="muted">Awaiting train_loss…</div>
      )}
    </div>
  );
}
