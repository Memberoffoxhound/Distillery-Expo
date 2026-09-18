import type { DistilleryEvent, StageName } from "../types/events";

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

export function IngestPane({ events }: { events: DistilleryEvent[] }) {
  const metrics = latestMetrics(events, "ingest");
  const frac = progressOf(events, "ingest");
  return (
    <>
      <div className="muted">dongle 3e2de7ed673817c2 · Connect + SSH</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${frac * 100}%` }} />
      </div>
      {metrics.length === 0 ? (
        <div className="muted">Awaiting route pull…</div>
      ) : (
        metrics.map(([k, v]) => (
          <div key={k} className="metric-row">
            <span className="k">{k}</span>
            <span className="v">{v}</span>
          </div>
        ))
      )}
    </>
  );
}

export function ShardPane({ events }: { events: DistilleryEvent[] }) {
  const frac = progressOf(events, "shard");
  const metrics = latestMetrics(events, "shard");
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
      {!metrics.length && <div className="muted">Shard packing idle</div>}
    </>
  );
}

export function TeacherPane({ events }: { events: DistilleryEvent[] }) {
  const metrics = latestMetrics(events, "teach");
  const frac = progressOf(events, "teach");
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
  return (
    <>
      <div className="muted">stock-modelV2 I/O student · tinygrad (stub)</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${frac * 100}%` }} />
      </div>
      <div className="loss-chart">
        {losses.length === 0 ? (
          <div className="empty" style={{ width: "100%" }}>
            loss curve…
          </div>
        ) : (
          losses.map((v, i) => (
            <div
              key={i}
              className="loss-bar"
              style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
              title={String(v)}
            />
          ))
        )}
      </div>
      {losses.length > 0 && (
        <div className="metric-row">
          <span className="k">train_loss</span>
          <span className="v">{losses.at(-1)?.toFixed(4)}</span>
        </div>
      )}
    </>
  );
}

export function EvalPane({ events }: { events: DistilleryEvent[] }) {
  const evals = latestMetrics(events, "eval");
  if (!evals.length) return <div className="empty">Scorecard pending</div>;
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

  return (
    <div className="flash-box">
      <h3>{done ? "Flash complete" : gated ? "Flash gated" : running ? "Flashing…" : "Flash standby"}</h3>
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
