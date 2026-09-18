import type { DistilleryEvent } from "../types/events";
import {
  latestDecision,
  latestStageStatus,
  progressOf,
  pct,
  readEvalPassed,
  readLiveFlag,
} from "../lib/eventSelectors";
import { EmptyState } from "./EmptyState";

/**
 * Flash pane — dual-gated on Craig/Graig contracts:
 *   eval_passed metric (1.0) AND flash stage gated → Confirm enabled.
 * Default eval_passed=false = not licensed. live=false = fixture/offline.
 * Never auto-flash. Looks-ready is not a road license.
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

  const evalPassed = readEvalPassed(events);
  const live = readLiveFlag(events);
  const fixture = live === false;

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
          body="We're training a driving agent. Confirm stays disabled until the student matches the teacher (eval_passed=true) and flash is gated. When licensed, Expo pushes driving_supercombo.onnx over SSH to mici — never auto."
          hint={
            ingestOnly
              ? "Ingest/shard jobs never unlock flash"
              : "eval_passed metric + flash gated · then your confirm"
          }
        />
        <p className="flash-copy muted">
          Expo is workstation mission control only. Never auto-write to mici.
        </p>
        <button className="danger" disabled title="Locked — eval_passed required">
          Confirm SSH push
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
          Confirm SSH push
        </button>
      </div>
    );
  }

  const headline = done
    ? "SSH push complete (simulated)"
    : running
      ? "Pushing over SSH…"
      : canConfirm
        ? fixture
          ? "Confirm carefully — live=false"
          : "Awaiting your confirm"
        : "Not licensed yet";

  const body = done
    ? "Simulated SSH push finished. Production writes driving_supercombo.onnx to mici over SSH after eval_passed and your confirm."
    : running
      ? "Pushing driving_supercombo.onnx over SSH (simulated). Expo stays on the workstation; mici gets a drop-in model."
      : canConfirm
        ? fixture
          ? "eval_passed=true on a live=false / fixture path. Confirm only simulates SSH push of driving_supercombo.onnx — not a road license."
          : "eval_passed=true (matches teacher). Confirm pushes driving_supercombo.onnx over SSH to mici as a drop-in replacement. Never auto-flash."
        : flashGated && !evalPassed
          ? "Flash is gated but eval_passed=false — student does not yet match teacher. Confirm stays locked."
          : "Flash stage is gated but eval has not passed — confirm stays locked.";

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
          {done ? "done" : running ? "pushing" : canConfirm ? "confirm" : "locked"}
        </span>
      </div>
      <p>{body}</p>
      <div className={`license-banner ${canConfirm && !fixture ? "ok" : "hold"}`}>
        {`eval_passed=${evalPassed} · live=${live === null ? "unknown" : live}`}
        {" — "}
        {fixture
          ? "fixture/offline — not a road license."
          : canConfirm
            ? "gate cleared — your confirm still required."
            : "not licensed yet — must match teacher driving first."}
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
              {detail ?? (done ? "done" : "pushing…")}
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
            ? "SSH push driving_supercombo.onnx to mici (simulated) — your confirm"
            : "Locked until eval_passed=true (matches teacher) and flash is gated"
        }
      >
        {done ? "Pushed" : running ? "Pushing…" : "Confirm SSH push"}
      </button>
    </div>
  );
}
