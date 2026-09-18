import type { DistilleryEvent, StageName } from "../types/events";
import { EmptyState } from "./EmptyState";

function latestMetrics(events: DistilleryEvent[], stage?: StageName) {
  const map = new Map<string, number>();
  for (const ev of events) {
    if (ev.kind !== "metric") continue;
    if (stage && ev.stage !== stage) continue;
    map.set(String(ev.payload.name), Number(ev.payload.value));
  }
  return [...map.entries()];
}

function progressOf(events: DistilleryEvent[], stage: StageName): number {
  let f = 0;
  for (const ev of events) {
    if (ev.kind === "progress" && ev.stage === stage) {
      f = Number(ev.payload.fraction ?? 0);
    }
  }
  return f;
}

export function ShardPane({ events }: { events: DistilleryEvent[] }) {
  const frac = progressOf(events, "shard");
  const metrics = latestMetrics(events, "shard");
  if (!metrics.length && frac === 0) {
    return (
      <EmptyState
        title="Shard packing idle"
        body="Segments become training shards after ingest. This stage is stubbed for M1."
        hint="Run the full demo to see packing progress."
      />
    );
  }
  return (
    <>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${frac * 100}%` }} />
      </div>
      {metrics.map(([k, v]) => (
        <div key={k} className="metric-row">
          <span className="k">{k}</span>
          <span className="v">{v}</span>
        </div>
      ))}
    </>
  );
}

export function TeacherPane({ events }: { events: DistilleryEvent[] }) {
  const metrics = latestMetrics(events, "teach");
  const frac = progressOf(events, "teach");
  if (!metrics.length && frac === 0) {
    return (
      <EmptyState
        title="Teacher standing by"
        body="Cinque/supercombo on the 7090 XT is not part of the M1 ingest slice."
        hint="No Chestnut · stock-modelV2 student later."
      />
    );
  }
  return (
    <>
      <div className="muted">Cinque/supercombo · 7090 XT · no Chestnut</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${frac * 100}%` }} />
      </div>
      {metrics.map(([k, v]) => (
        <div key={k} className="metric-row">
          <span className="k">{k}</span>
          <span className="v">{v}</span>
        </div>
      ))}
    </>
  );
}

export function TrainPane({ events }: { events: DistilleryEvent[] }) {
  const losses = events
    .filter((e) => e.kind === "metric" && e.payload.name === "train_loss")
    .map((e) => Number(e.payload.value));
  const max = Math.max(...losses, 0.01);
  const frac = progressOf(events, "train");
  if (!losses.length && frac === 0) {
    return (
      <EmptyState
        title="Student train idle"
        body="Loss curves appear once the stock-modelV2 I/O student starts (stub in M1)."
      />
    );
  }
  return (
    <>
      <div className="muted">stock-modelV2 I/O student · tinygrad (stub)</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${frac * 100}%` }} />
      </div>
      <div className="loss-chart">
        {losses.map((v, i) => (
          <div
            key={i}
            className="loss-bar"
            style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
            title={String(v)}
          />
        ))}
      </div>
      {losses.length > 0 && (
        <div className="metric-row">
          <span className="k">train_loss</span>
          <span className="v">{losses[losses.length - 1]?.toFixed(4)}</span>
        </div>
      )}
    </>
  );
}

export function EvalPane({ events }: { events: DistilleryEvent[] }) {
  const evals = latestMetrics(events, "eval");
  if (!evals.length) {
    return (
      <EmptyState
        title="Scorecard pending"
        body="Eval metrics land here after export. Nothing to grade until a full demo or later milestones."
      />
    );
  }
  return (
    <div className="tiles">
      {evals.map(([k, v]) => (
        <div key={k} className={`tile ${v >= 0.9 || k.includes("mae") ? "pass" : ""}`}>
          <div className="name">{k}</div>
          <div className="val">{typeof v === "number" ? v.toFixed(3) : v}</div>
        </div>
      ))}
    </div>
  );
}

export function FlashPane({
  status,
  events,
  onConfirm,
}: {
  status: string;
  events: DistilleryEvent[];
  onConfirm: () => void;
}) {
  const gated = status === "gated" || events.some(
    (e) => e.kind === "stage" && e.stage === "flash" && e.payload.status === "gated"
  );
  const done = events.some(
    (e) => e.kind === "stage" && e.stage === "flash" && e.payload.status === "done"
  );
  const running = events.some(
    (e) => e.kind === "stage" && e.stage === "flash" && e.payload.status === "running"
  );
  const frac = progressOf(events, "flash");
  const ingestOnly =
    events.length > 0 &&
    !events.some((e) => e.stage === "flash") &&
    events.some((e) => e.stage === "ingest");

  if (!gated && !running && !done) {
    return (
      <div className="flash-box">
        <h3>Flash standby</h3>
        <p>
          Design lock: never auto-flash. Confirm only after eval gate passes.
          Target: mici / QCOM · stock-modelV2 I/O artifact.
        </p>
        {ingestOnly ? (
          <p className="muted">
            Ingest-only jobs do not reach flash — confirm stays disabled.
          </p>
        ) : (
          <p className="muted">
            Waiting for the pipeline to gate flash after a passing eval.
          </p>
        )}
        <button className="danger" disabled>
          Confirm flash
        </button>
      </div>
    );
  }

  return (
    <div className="flash-box">
      <h3>{done ? "Flash complete" : gated ? "Flash gated" : "Flashing…"}</h3>
      <p>
        Design lock: never auto-flash. Confirm only after eval gate passes.
        Target: mici / QCOM · stock-modelV2 I/O artifact.
      </p>
      {(running || done) && (
        <div className="bar-track">
          <div className="bar-fill" style={{ width: `${(done ? 1 : frac) * 100}%` }} />
        </div>
      )}
      <button
        className="danger"
        disabled={!gated || done}
        onClick={onConfirm}
      >
        {done ? "Flashed" : "Confirm flash"}
      </button>
    </div>
  );
}
