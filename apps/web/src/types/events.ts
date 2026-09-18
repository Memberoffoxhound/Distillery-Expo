export type StageName =
  | "ingest"
  | "shard"
  | "teach"
  | "train"
  | "export"
  | "eval"
  | "flash";

export type EventKind =
  | "decision"
  | "metric"
  | "warning"
  | "sample"
  | "log"
  | "progress"
  | "stage";

export interface DistilleryEvent {
  id: string;
  ts: string;
  job_id: string;
  kind: EventKind;
  stage?: StageName | null;
  payload: Record<string, unknown>;
}

export const STAGES: StageName[] = [
  "ingest",
  "shard",
  "teach",
  "train",
  "export",
  "eval",
  "flash",
];

export type StageStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "gated"
  | "skipped";
