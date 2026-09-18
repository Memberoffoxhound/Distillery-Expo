import { useEffect, useRef } from "react";
import type { DistilleryEvent } from "../types/events";

export function LogsPane({ events }: { events: DistilleryEvent[] }) {
  const logs = events.filter((e) => e.kind === "log" || e.kind === "warning");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (!logs.length) return <div className="empty">No logs yet</div>;

  return (
    <div>
      {logs.map((ev) => {
        const level =
          ev.kind === "warning"
            ? "warn"
            : String(ev.payload.level ?? "info");
        const msg =
          ev.kind === "warning"
            ? String(ev.payload.message ?? "")
            : String(ev.payload.message ?? "");
        const src = String(ev.payload.source ?? ev.stage ?? "");
        const ts = new Date(ev.ts).toLocaleTimeString();
        return (
          <div key={ev.id} className={`log-line ${level}`}>
            <span className="ts">{ts}</span>
            <span className="src">[{src}]</span>
            {msg}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
