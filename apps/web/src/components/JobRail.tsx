import { STAGES, type StageName, type StageStatus } from "../types/events";

const labels: Record<StageName, string> = {
  ingest: "Ingest",
  shard: "Shard",
  teach: "Teach",
  train: "Train",
  export: "Export",
  eval: "Eval",
  flash: "Flash",
};

export function JobRail({
  stageStatus,
}: {
  stageStatus: Record<StageName, StageStatus>;
}) {
  return (
    <div className="rail">
      {STAGES.map((s, i) => (
        <span key={s} style={{ display: "contents" }}>
          {i > 0 && <span className="rail-arrow">›</span>}
          <div className={`rail-step ${stageStatus[s]}`}>
            <span className="dot" />
            {labels[s]}
          </div>
        </span>
      ))}
    </div>
  );
}
