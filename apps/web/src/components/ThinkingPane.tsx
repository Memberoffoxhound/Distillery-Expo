import type { DistilleryEvent } from "../types/events";

export function ThinkingPane({ events }: { events: DistilleryEvent[] }) {
  const decisions = events.filter((e) => e.kind === "decision").slice().reverse();

  if (!decisions.length) {
    return <div className="empty">Decision timeline idle — start a demo</div>;
  }

  return (
    <div className="thinking-list">
      {decisions.map((ev) => {
        const p = ev.payload;
        const title = String(p.title ?? "Decision");
        const rationale = String(p.rationale ?? "");
        const options = (p.options_considered as string[]) || [];
        const chosen = p.chosen as string | undefined;
        const confidence = p.confidence as number | undefined;
        const ts = new Date(ev.ts).toLocaleTimeString();
        return (
          <article key={ev.id} className="thought">
            <div className="head">
              <span className="title">{title}</span>
              <span className="meta">
                {ev.stage ?? "—"} · {ts}
                {confidence != null ? (
                  <span className="confidence"> · conf {(confidence * 100).toFixed(0)}%</span>
                ) : null}
              </span>
            </div>
            <p className="rationale">{rationale}</p>
            <div className="opts">
              {options.map((o) => (
                <span key={o} className={`chip ${o === chosen ? "chosen" : ""}`}>
                  {o === chosen ? "✓ " : ""}
                  {o}
                </span>
              ))}
            </div>
          </article>
        );
      })}
    </div>
  );
}
