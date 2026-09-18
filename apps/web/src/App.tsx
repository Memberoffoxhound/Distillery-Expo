import { useEffect, useRef } from "react";
import { JobRail } from "./components/JobRail";
import { Pane } from "./components/Pane";
import { ThinkingPane } from "./components/ThinkingPane";
import { CamsPane } from "./components/CamsPane";
import { LogsPane } from "./components/LogsPane";
import {
  EvalPane,
  FlashPane,
  IngestPane,
  ShardPane,
  TeacherPane,
  TrainPane,
} from "./components/MetricsBits";
import { useJobStream } from "./hooks/useJobStream";
import "./styles/app.css";

export default function App() {
  const job = useJobStream();
  const autoStarted = useRef(false);
  const startDemo = job.startDemo;

  useEffect(() => {
    if (autoStarted.current) return;
    autoStarted.current = true;
    const t = setTimeout(() => startDemo(), 400);
    return () => clearTimeout(t);
  }, [startDemo]);

  const pillClass =
    job.status === "gated"
      ? "gated"
      : job.connected || job.status === "running"
        ? "live"
        : "";

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
          <span className={`status-pill ${pillClass}`}>
            {job.error
              ? `err: ${job.error}`
              : job.jobId
                ? `${job.status} · ${job.jobId.slice(0, 8)}`
                : "idle"}
          </span>
          <button className="primary" onClick={() => job.startDemo()}>
            Run demo
          </button>
        </div>
      </header>

      <JobRail stageStatus={job.stageStatus} />

      <main className="grid">
        <Pane title="Ingest" tag="Connect" className="ingest">
          <IngestPane events={job.events} />
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
