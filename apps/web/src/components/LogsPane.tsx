import { useEffect, useRef } from "react";
import type { DistilleryEvent } from "../types/events";
import { EmptyState } from "./EmptyState";

export function LogsPane({ events }: { events: DistilleryEvent[] }) {
  const logs = events.filter((e) => e.kind === "log" || e.kind === "warning");
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  if (!logs.length) {
    return (
      <EmptyState
        title="Log stream empty"
        body="Stage messages from ingest and the demo land here as the job runs."
      />
    );
  }

  return (
    <div>
      {logs.map((ev) => {
        const level =
          ev.kind === "warning"
            ? "warn"
            : String(ev.payload.level ?? "info");
        const msg = String(ev.payload.message ?? "");
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
