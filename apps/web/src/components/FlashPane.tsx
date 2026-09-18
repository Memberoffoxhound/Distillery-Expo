import type { DistilleryEvent } from "../types/events";
import {
  latestDecision,
  latestStageStatus,
  progressOf,
  pct,
  stageDone,
} from "../lib/eventSelectors";
import { EmptyState } from "./EmptyState";

/**
 * Flash pane — dual-gated: eval must pass AND flash stage must be gated
 * before Confirm is enabled. Never auto-flash. Never looks “ready to write”
 * while locked.
 *
 * Flash = write mici-fit ONNX student to the device later.
 * Expo = workstation mission control only — not Expo-on-mici.
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

  const evalPassed = stageDone(events, "eval");
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

  /** Confirm only when BOTH gates clear: eval done + flash gated. */
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
          title="Flash locked"
          body="Flash writes the mici-fit ONNX student to the device later — not Expo-on-mici. Confirm stays disabled until eval passes and the pipeline gates flash."
          hint={
            ingestOnly
              ? "Ingest/shard jobs never unlock flash"
              : "Eval pass + flash gated · then confirm"
          }
        />
        <p className="flash-copy muted">
          Design lock: never auto-flash. Expo is workstation mission control only.
        </p>
        <button
          className="danger"
          disabled
          title="Locked — eval must pass and flash must be gated"
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
          No confirm received. Nothing was written to the device. Expo remains
          mission control only.
        </p>
        <button className="danger" disabled>
          Confirm flash
        </button>
      </div>
    );
  }

  const headline = done
    ? "Flash complete"
    : running
      ? "Writing to device…"
      : canConfirm
        ? "Awaiting your confirm"
        : "Flash gated";

  const body = done
    ? "Simulated write finished. Real mici / QCOM flash lands in a later milestone."
    : running
      ? "Transferring the mici-fit ONNX student (simulated). Expo stays on the workstation."
      : canConfirm
        ? "Eval passed. Confirm to write the stock-modelV2 I/O ONNX student to mici / QCOM. Never auto-flash."
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
            ? "Write mici-fit ONNX student to device (simulated)"
            : "Locked until eval passes and flash is gated"
        }
      >
        {done ? "Flashed" : running ? "Writing…" : "Confirm flash"}
      </button>
    </div>
  );
}
