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

/** Scorecard pass heuristic aligned with demo flash-gate thresholds. */
function isPass(name: string, value: number): boolean {
  const n = name.toLowerCase();
  if (n.includes("mae")) return value <= 0.08;
  return value >= 0.9;
}

/**
 * Eval pane — clear scorecard when stage=eval metrics exist.
 * Empty stays calm “scorecard pending”. Binds progress / metric / stage / decision.
 * Future: Craig /jobs/eval can feed the same event kinds.
 */
export function EvalPane({ events }: { events: DistilleryEvent[] }) {
  const evals = latestMetrics(events, "eval");
  const { fraction, detail } = progressOf(events, "eval");
  const stage = latestStageStatus(events, "eval");
  const decision = latestDecision(events, "eval");
  const signal = hasStageSignal(events, "eval");

  const exportDone = stageDone(events, "export");
  const exportRunning = stageRunning(events, "export");
  const trainDone = stageDone(events, "train");

  if (!signal && evals.length === 0) {
    if (exportRunning) {
      return (
        <EmptyState
          title="Scorecard pending"
          body="Export is still in flight. Offline metrics land here once eval events stream."
          hint="stage=export → stage=eval"
        />
      );
    }
    if (exportDone || trainDone) {
      return (
        <EmptyState
          title="Scorecard pending"
          body="Waiting for offline eval. This pane stays quiet until eval metrics or stage events arrive."
          hint="Run demo streams eval · /jobs/eval later"
        />
      );
    }
    return (
      <EmptyState
        title="Scorecard pending"
        body="Eval metrics land here after export. Nothing to grade until a full demo or later milestones."
        hint="stage=eval · metric / progress / stage"
      />
    );
  }

  const status = stage?.status ?? (evals.length > 0 ? "done" : "running");
  const statusLabel =
    status === "done"
      ? "ready"
      : status === "failed"
        ? "failed"
        : status === "running"
          ? "scoring"
          : status;
  const headline =
    stage?.detail ??
    (status === "done"
      ? "Offline scorecard"
      : status === "failed"
        ? "Eval failed"
        : "Scoring student");
  const showBar =
    (status === "running" || status === "done" || fraction > 0) &&
    evals.length === 0;
  const barWidth = status === "done" ? 1 : fraction;

  return (
    <div className="stage-pane eval-pane">
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
          <div className="muted">Offline scorecard · flash gate input</div>
        )}
      </div>

      {showBar && (
        <div className="stage-progress">
          <div className="bar-track" aria-hidden>
            <div className="bar-fill" style={{ width: `${barWidth * 100}%` }} />
          </div>
          <div className="stage-progress-meta">
            <span className="mono">{pct(barWidth)}</span>
            <span className="muted">{detail ?? "scoring…"}</span>
          </div>
        </div>
      )}

      {evals.length > 0 ? (
        <div className="tiles">
          {evals.map(([k, { value }]) => {
            const pass = isPass(k, value);
            return (
              <div key={k} className={`tile ${pass ? "pass" : ""}`}>
                <div className="name">{k}</div>
                <div className="val">
                  {typeof value === "number" ? value.toFixed(3) : value}
                </div>
              </div>
            );
          })}
        </div>
      ) : status === "running" ? (
        <div className="muted">Scorecard pending…</div>
      ) : null}
    </div>
  );
}
