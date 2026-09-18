import { JobRail } from "./components/JobRail";
import { Pane } from "./components/Pane";
import { ThinkingPane } from "./components/ThinkingPane";
import { CamsPane } from "./components/CamsPane";
import { LogsPane } from "./components/LogsPane";
import { IngestPane } from "./components/IngestPane";
import { ShardPane } from "./components/ShardPane";
import {
  EvalPane,
  FlashPane,
  TeacherPane,
  TrainPane,
} from "./components/MetricsBits";
import { useJobStream } from "./hooks/useJobStream";
import "./styles/app.css";

export default function App() {
  const job = useJobStream();

  const busy =
    job.status === "pending" ||
    job.status === "running" ||
    job.status === "gated";

  const pillClass =
    job.status === "gated"
      ? "gated"
      : job.status === "failed"
        ? "failed"
        : job.connected || job.status === "running"
          ? "live"
          : "";

  const statusLabel = job.error
    ? `err: ${job.error}`
    : job.jobId
      ? `${job.jobKind ?? "job"} · ${job.status} · ${job.jobId.slice(0, 8)}`
      : "idle";

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-mark" />
          <div>
            <h1>Distillery Expo</h1>
            <span>mici · Cinque/7090 XT · stock-modelV2 student</span>
          </div>
        </div>
        <div className="header-actions">
          <span className={`status-pill ${pillClass}`}>{statusLabel}</span>
          <button
            className="primary"
            disabled={busy}
            onClick={() => job.startIngest({ source: "fixture" })}
            title="POST /jobs/ingest {source:fixture}"
          >
            Pull mici route
          </button>
          <button
            disabled={busy}
            onClick={() => job.startDemo()}
            title="Full M0 staged demo (flash stays gated)"
          >
            Run demo
          </button>
        </div>
      </header>

      <JobRail
        stageStatus={job.stageStatus}
        stageTiming={job.stageTiming}
        jobKind={job.jobKind}
      />

      <main className="grid">
        <Pane title="Ingest" tag="mici routes" className="ingest">
          <IngestPane
            events={job.events}
            busy={busy}
            onIngest={({ source, routeId }) =>
              job.startIngest({ source, routeId })
            }
          />
        </Pane>
        <Pane title="Cams" tag="road / wide / driver" className="cams">
          <CamsPane events={job.events} />
        </Pane>
        <Pane title="Shard" tag="pack" className="shard">
          <ShardPane events={job.events} />
        </Pane>
        <Pane title="Teacher" tag="7090 XT" className="teacher">
          <TeacherPane events={job.events} />
        </Pane>
        <Pane title="Train" tag="loss" className="train">
          <TrainPane events={job.events} />
        </Pane>
        <Pane title="Thinking" tag="decision timeline" className="thinking">
          <ThinkingPane events={job.events} />
        </Pane>
        <Pane title="Logs" tag="stream" className="logs">
          <LogsPane events={job.events} />
        </Pane>
        <Pane title="Eval" tag="scorecard" className="eval">
          <EvalPane events={job.events} />
        </Pane>
        <Pane title="Flash" tag="gated" className="flash">
          <FlashPane
            status={job.status}
            events={job.events}
            onConfirm={job.confirmFlash}
          />
        </Pane>
      </main>
    </div>
  );
}
