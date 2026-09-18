import type { DistilleryEvent } from "../types/events";
import {
  latestDecision,
  latestMetrics,
  latestStageStatus,
  progressOf,
  pct,
  stageDone,
} from "../lib/eventSelectors";
import { EmptyState } from "./EmptyState";

function isPass(name: string, value: number): boolean {
  const n = name.toLowerCase();
  if (n.includes("mae")) return value <= 0.08;
  return value >= 0.9;
}

/** Eval clears the second lock only when scorecard numbers exist and pass. */
function evalClearsLicense(events: DistilleryEvent[]): boolean {
  if (!stageDone(events, "eval")) return false;
  const metrics = latestMetrics(events, "eval");
  if (metrics.length === 0) return false;
  return metrics.every(([k, { value }]) => isPass(k, value));
}

function isFixturePath(events: DistilleryEvent[]): boolean {
  return events.some((ev) => {
    const p = ev.payload as Record<string, unknown>;
    if (p.live === false) return true;
    const meta = (p.meta as Record<string, unknown> | undefined) ?? {};
    return meta.fixture === true || meta.live === false;
  });
}

/**
 * Flash pane — dual-gated: eval scorecard must CLEAR and flash must be gated
 * before Confirm is enabled. Never auto-flash. Never looks road-ready on a stub.
 *
 * We're shipping a driving agent — a mici-fit ONNX that only looks ready is a
 * teenager with a permit: not shippable without eval + your confirm.
 */
export function FlashPane({
  status,
  events,
  onConfirm,
}: {
  status: string;
  events: DistilleryEvent[];
  onConfirm: () => void;
}) {
  const stage = latestStageStatus(events, "flash");
  const decision = latestDecision(events, "flash");
  const { fraction, detail } = progressOf(events, "flash");
  const fixture = isFixturePath(events);

  const evalPassed = evalClearsLicense(events);
  const flashGatedFromEvents = events.some(
    (e) =>
      e.kind === "stage" &&
      e.stage === "flash" &&
      e.payload.status === "gated"
  );
  const flashGated = status === "gated" || flashGatedFromEvents;

  const done =
    stage?.status === "done" ||
    events.some(
      (e) =>
        e.kind === "stage" &&
        e.stage === "flash" &&
        e.payload.status === "done"
    );
  const skipped =
    stage?.status === "skipped" ||
    events.some(
      (e) =>
        e.kind === "stage" &&
        e.stage === "flash" &&
        e.payload.status === "skipped"
    );
  const running =
    stage?.status === "running" ||
    events.some(
      (e) =>
        e.kind === "stage" &&
        e.stage === "flash" &&
        e.payload.status === "running"
    );

  /** Confirm only when BOTH gates clear: eval scorecard pass + flash gated. */
  const canConfirm = flashGated && evalPassed && !done && !running && !skipped;

  const ingestOnly =
    events.length > 0 &&
    !events.some((e) => e.stage === "flash" || e.stage === "eval") &&
    events.some((e) => e.stage === "ingest" || e.stage === "shard");

  const lockedIdle = !flashGated && !running && !done && !skipped;

  if (lockedIdle) {
    return (
      <div className="flash-box flash-locked">
        <EmptyState
          title="Not licensed yet"
          body="We're training a driving agent. Flash writes a mici-fit ONNX student to the device later — never auto, never on looks-ready alone. Confirm stays disabled until the scorecard clears and the pipeline gates flash."
          hint={
            ingestOnly
              ? "Ingest/shard jobs never unlock flash"
              : "Eval numbers clear + flash gated · then your confirm"
          }
        />
        <p className="flash-copy muted">
          No teenagers with permits. Expo is workstation mission control only.
        </p>
        <button
          className="danger"
          disabled
          title="Locked — scorecard must clear and flash must be gated"
        >
          Confirm flash
        </button>
      </div>
    );
  }

  if (skipped) {
    return (
      <div className="flash-box flash-skipped">
        <h3>Flash skipped</h3>
        <p>
          No confirm received. Nothing was written to the device. The student
          stays unlicensed for on-road use.
        </p>
        <button className="danger" disabled>
          Confirm flash
        </button>
      </div>
    );
  }

  const headline = done
    ? "Flash complete (simulated)"
    : running
      ? "Writing to device…"
      : canConfirm
        ? fixture
          ? "Confirm carefully — fixture path"
          : "Awaiting your confirm"
        : "Not licensed yet";

  const body = done
    ? "Simulated write finished. Real mici / QCOM flash still requires a cleared scorecard and your confirm in production."
    : running
      ? "Transferring the mici-fit ONNX student (simulated). Expo stays on the workstation."
      : canConfirm
        ? fixture
          ? "Scorecard cleared on a fixture/offline path (live=false). Confirm only if you mean a simulated write — this is not a road license."
          : "Scorecard cleared. Confirm to write the stock-modelV2 I/O ONNX student to mici / QCOM. Never auto-flash."
        : flashGated && !evalPassed
          ? "Flash is gated but the scorecard has not cleared — looks-ready is not licensed. Confirm stays locked."
          : "Flash stage is gated but eval has not passed yet — confirm stays locked.";

  const showBar = running || done;
  const barWidth = done ? 1 : fraction;

  return (
    <div
      className={`flash-box ${canConfirm ? "flash-armed" : running || done ? "flash-active" : "flash-locked"}`}
    >
      <div className="stage-title-row">
        <h3>{headline}</h3>
        <span
          className={`stage-status ${done ? "done" : running ? "running" : canConfirm ? "gated" : "gated"}`}
        >
          {done ? "done" : running ? "writing" : canConfirm ? "confirm" : "locked"}
        </span>
      </div>
      <p>{body}</p>
      <div className={`license-banner ${canConfirm && !fixture ? "ok" : "hold"}`}>
        {fixture
          ? "Fixture / offline — not a road license."
          : canConfirm
            ? "Gate cleared — your confirm is still required. Never auto-write."
            : "Not licensed yet — no teenagers with permits."}
      </div>
      {decision?.chosen && (
        <div className="stage-decision muted">
          <span className="k">{decision.title}</span>
          <span className="v mono">{decision.chosen}</span>
        </div>
      )}
      {showBar && (
        <div className="stage-progress">
          <div className="bar-track" aria-hidden>
            <div className="bar-fill" style={{ width: `${barWidth * 100}%` }} />
          </div>
          <div className="stage-progress-meta">
            <span className="mono">{pct(barWidth)}</span>
            <span className="muted">
              {detail ?? (done ? "done" : "writing…")}
            </span>
          </div>
        </div>
      )}
      <button
        className="danger"
        disabled={!canConfirm}
        onClick={onConfirm}
        title={
          canConfirm
            ? "Write mici-fit ONNX student to device (simulated) — your confirm"
            : "Locked until scorecard clears and flash is gated"
        }
      >
        {done ? "Flashed" : running ? "Writing…" : "Confirm flash"}
      </button>
    </div>
  );
}
