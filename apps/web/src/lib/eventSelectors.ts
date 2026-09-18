import type { DistilleryEvent, StageName, StageStatus } from "../types/events";

export function latestMetrics(
  events: DistilleryEvent[],
  stage?: StageName
): [string, { value: number; unit?: string }][] {
  const map = new Map<string, { value: number; unit?: string }>();
  for (const ev of events) {
    if (ev.kind !== "metric") continue;
    if (stage && ev.stage !== stage) continue;
    map.set(String(ev.payload.name), {
      value: Number(ev.payload.value),
      unit: ev.payload.unit as string | undefined,
    });
  }
  return [...map.entries()];
}

export function progressOf(
  events: DistilleryEvent[],
  stage: StageName
): { fraction: number; detail?: string } {
  let fraction = 0;
  let detail: string | undefined;
  for (const ev of events) {
    if (ev.kind === "progress" && ev.stage === stage) {
      fraction = Number(ev.payload.fraction ?? 0);
      const d = ev.payload.detail;
      detail = typeof d === "string" && d.length > 0 ? d : undefined;
    }
  }
  return { fraction, detail };
}

export function latestStageStatus(
  events: DistilleryEvent[],
  stage: StageName
): { status: StageStatus; detail?: string } | null {
  let hit: { status: StageStatus; detail?: string } | null = null;
  for (const ev of events) {
    if (ev.kind !== "stage" || ev.stage !== stage) continue;
    const status = String(ev.payload.status ?? "") as StageStatus;
    if (!status) continue;
    const d = ev.payload.detail;
    hit = {
      status,
      detail: typeof d === "string" && d.length > 0 ? d : undefined,
    };
  }
  return hit;
}

export function latestDecision(
  events: DistilleryEvent[],
  stage: StageName
): { title: string; chosen?: string; rationale?: string } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]!;
    if (ev.kind !== "decision" || ev.stage !== stage) continue;
    return {
      title: String(ev.payload.title ?? "Decision"),
      chosen:
        typeof ev.payload.chosen === "string" ? ev.payload.chosen : undefined,
      rationale:
        typeof ev.payload.rationale === "string"
          ? ev.payload.rationale
          : undefined,
    };
  }
  return null;
}

export function hasStageSignal(
  events: DistilleryEvent[],
  stage: StageName
): boolean {
  return events.some(
    (e) =>
      e.stage === stage &&
      (e.kind === "stage" ||
        e.kind === "progress" ||
        e.kind === "metric" ||
        e.kind === "decision" ||
        e.kind === "sample" ||
        e.kind === "log" ||
        e.kind === "warning")
  );
}

export function metricSeries(
  events: DistilleryEvent[],
  stage: StageName,
  name: string
): number[] {
  return events
    .filter(
      (e) =>
        e.kind === "metric" &&
        e.stage === stage &&
        e.payload.name === name
    )
    .map((e) => Number(e.payload.value));
}

export function pct(frac: number): string {
  return `${Math.round(Math.min(1, Math.max(0, frac)) * 100)}%`;
}

export function stageDone(
  events: DistilleryEvent[],
  stage: StageName
): boolean {
  return events.some(
    (e) =>
      e.kind === "stage" &&
      e.stage === stage &&
      e.payload.status === "done"
  );
}

export function stageRunning(
  events: DistilleryEvent[],
  stage: StageName
): boolean {
  return events.some(
    (e) =>
      e.kind === "stage" &&
      e.stage === stage &&
      e.payload.status === "running"
  );
}

/** Prefer Graig/Craig metric name=eval_passed (1.0/0.0). Default false = not licensed. */
export function readEvalPassed(events: DistilleryEvent[]): boolean {
  let passed = false;
  let seen = false;
  for (const ev of events) {
    if (ev.kind !== "metric") continue;
    const name = String(ev.payload.name ?? "");
    if (name !== "eval_passed" && name !== "eval_pass") continue;
    seen = true;
    passed = Number(ev.payload.value ?? 0) >= 1.0;
  }
  if (seen) return passed;
  // Decision rationale may carry eval_passed=true/false
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]!;
    if (ev.kind !== "decision" || ev.stage !== "eval") continue;
    const blob = `${ev.payload.rationale ?? ""} ${ev.payload.chosen ?? ""}`;
    if (/eval_passed\s*=\s*true/i.test(blob)) return true;
    if (/eval_passed\s*=\s*false/i.test(blob)) return false;
  }
  return false;
}

/** live=false (or fixture meta) means offline / not a road license. */
export function readLiveFlag(events: DistilleryEvent[]): boolean | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]!;
    const p = ev.payload as Record<string, unknown>;
    if (typeof p.live === "boolean") return p.live;
    const meta = (p.meta as Record<string, unknown> | undefined) ?? {};
    if (typeof meta.live === "boolean") return meta.live;
    if (meta.fixture === true) return false;
  }
  return null;
}

