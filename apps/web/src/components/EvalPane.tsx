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

function isFixtureOrOffline(events: DistilleryEvent[]): boolean {
  for (const ev of events) {
    if (ev.stage !== "eval" && ev.stage !== "export" && ev.stage !== "train") {
      continue;
    }
    const p = ev.payload as Record<string, unknown>;
    if (p.live === false) return true;
    const meta = (p.meta as Record<string, unknown> | undefined) ?? {};
    if (meta.fixture === true || meta.live === false) return true;
    if (typeof p.label === "string" && /fixture|offline|stub/i.test(p.label)) {
      return true;
    }
  }
  // Demo / soft-label path is not a live road license
  return events.some(
    (e) =>
      e.kind === "log" &&
      typeof e.payload.message === "string" &&
      /fixture|soft-label|no 7090|offline/i.test(String(e.payload.message))
  );
}

/**
 * Eval pane — scorecard for a driving agent. Never greenwashes a stub into
 * "road ready." Fixture / live=false stays labeled. Flash gate needs real numbers.
 */
export function EvalPane({ events }: { events: DistilleryEvent[] }) {
  const evals = latestMetrics(events, "eval");
  const { fraction, detail } = progressOf(events, "eval");
  const stage = latestStageStatus(events, "eval");
  const decision = latestDecision(events, "eval");
  const signal = hasStageSignal(events, "eval");
  const fixture = isFixtureOrOffline(events);

  const exportDone = stageDone(events, "export");
  const exportRunning = stageRunning(events, "export");
  const trainDone = stageDone(events, "train");

  if (!signal && evals.length === 0) {
    if (exportRunning) {
      return (
        <EmptyState
          title="Scorecard pending"
          body="Export is still in flight. Offline metrics land here once eval events stream — no license until numbers exist."
          hint="stage=export → stage=eval"
        />
      );
    }
    if (exportDone || trainDone) {
      return (
        <EmptyState
          title="Scorecard pending"
          body="Waiting for offline eval. A driving agent without numbers is not licensed — this pane stays quiet until metrics arrive."
          hint="Run demo streams eval · /jobs/eval later"
        />
      );
    }
    return (
      <EmptyState
        title="Scorecard pending"
        body="Eval grades the student before any mici write. Nothing to show until metrics stream — we do not invent a pass."
        hint="stage=eval · metric / progress / stage"
      />
    );
  }

  const status = stage?.status ?? (evals.length > 0 ? "done" : "running");
  const allPass =
    evals.length > 0 && evals.every(([k, { value }]) => isPass(k, value));
  const statusLabel =
    status === "done"
      ? fixture
        ? "fixture"
        : allPass
          ? "cleared"
          : "hold"
      : status === "failed"
        ? "failed"
        : status === "running"
          ? "scoring"
          : status;
  const headline =
    stage?.detail ??
    (status === "done"
      ? fixture
        ? "Offline scorecard · not licensed"
        : allPass
          ? "Scorecard cleared gate"
          : "Scorecard hold — not licensed"
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
          <div className="muted">
            Driving-agent scorecard · flash gate input · never a fake pass
          </div>
        )}
      </div>

      {(fixture || (evals.length > 0 && !allPass) || status === "done") && (
        <div className={`license-banner ${fixture || !allPass ? "hold" : "ok"}`}>
          {fixture
            ? "Not licensed yet — fixture / offline path (live=false). Looks ready ≠ road ready."
            : !allPass && evals.length > 0
              ? "Not licensed yet — scorecard hold. Do not treat this student as road-ready."
              : allPass
                ? "Gate numbers cleared — still requires your flash confirm. Never auto-write to mici."
                : "Not licensed yet — waiting on complete scorecard numbers."}
        </div>
      )}

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
              <div key={k} className={`tile ${pass ? "pass" : "fail"}`}>
                <div className="name">{k}</div>
                <div className="val">
                  {typeof value === "number" ? value.toFixed(3) : value}
                </div>
                <div className="tile-mark">{pass ? "clear" : "hold"}</div>
              </div>
            );
          })}
        </div>
      ) : status === "running" ? (
        <div className="muted">Scorecard pending — no numbers, no license…</div>
      ) : null}
    </div>
  );
}
