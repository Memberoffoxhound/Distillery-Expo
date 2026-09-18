import { useCallback, useState } from "react";
import {
  checkReadiness,
  type ReadinessCheck,
  type ReadinessReport,
} from "../lib/readiness";
import type { RouteSource } from "../lib/api";

/**
 * Primary simple-user action: Start training.
 * Preflight asks calmly in the UI when something is missing.
 * Orchestrates via POST /jobs/pipeline (discover→…→eval; flash stays gated).
 * Fixture path always labeled — never silent.
 */
export function StartTraining({
  busy,
  onStart,
}: {
  busy: boolean;
  onStart: (opts: { source: RouteSource; includeFlash?: boolean }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runCheck = useCallback(async () => {
    setChecking(true);
    setError(null);
    setOpen(true);
    try {
      const r = await checkReadiness();
      setReport(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Readiness check failed");
      setReport(null);
    } finally {
      setChecking(false);
    }
  }, []);

  const startLive = () => {
    if (!report) return;
    onStart({
      source:
        report.suggestedSource === "fixture" ? "auto" : report.suggestedSource,
      includeFlash: true,
    });
    setOpen(false);
  };

  const startFixture = () => {
    onStart({ source: "fixture", includeFlash: true });
    setOpen(false);
  };

  const missing = report?.checks.filter((c) => c.status !== "ok") ?? [];

  return (
    <div className="start-training-wrap">
      <button
        className="primary start-training-btn"
        disabled={busy || checking}
        onClick={() => void runCheck()}
        title="Check readiness, then POST /jobs/pipeline — flash stays gated"
      >
        {checking ? "Checking…" : "Start training"}
      </button>

      {open && (
        <div
          className="readiness-panel"
          role="dialog"
          aria-label="Training readiness"
        >
          <div className="readiness-head">
            <div>
              <div className="readiness-title">Before we train</div>
              <div className="muted">
                Discover → ingest → shards → teach → train → export → eval.
                Flash stays gated (teacher-parity).
              </div>
            </div>
            <button
              type="button"
              className="readiness-close"
              onClick={() => setOpen(false)}
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          {error && <div className="ingest-error">{error}</div>}

          {checking && !report && (
            <div className="muted">
              Checking Connect, LAN/ADB, hours, device, teacher…
            </div>
          )}

          {report && (
            <>
              <ul className="readiness-list">
                {report.checks.map((c) => (
                  <ReadinessRow key={c.id} check={c} />
                ))}
              </ul>

              {report.readyLive ? (
                <div className="readiness-ok muted">
                  Ready for live path via {report.suggestedSource}.
                </div>
              ) : (
                <div className="readiness-ask">
                  <div className="readiness-ask-title">Still need a few things</div>
                  <ul>
                    {missing.map((c) =>
                      c.ask ? (
                        <li key={c.id}>
                          <strong>{c.label}:</strong> {c.ask}
                        </li>
                      ) : null
                    )}
                  </ul>
                </div>
              )}

              <div className="readiness-actions">
                {report.readyLive ? (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={startLive}
                    title="POST /jobs/pipeline with live/auto source"
                  >
                    Start live training
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={startLive}
                    title="Try pipeline with best available source"
                  >
                    Try anyway
                  </button>
                )}
                <button
                  className="fixture-btn"
                  disabled={busy}
                  onClick={startFixture}
                  title="Labeled fixture pipeline — not live / not licensed flash"
                >
                  Start fixture (labeled)
                </button>
                <button
                  type="button"
                  disabled={checking}
                  onClick={() => void runCheck()}
                >
                  Recheck
                </button>
              </div>
              <p className="readiness-footnote muted">
                Fixture is always labeled offline. Flash never auto-writes — eval
                gate + confirm.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ReadinessRow({ check }: { check: ReadinessCheck }) {
  return (
    <li className={`readiness-row status-${check.status}`}>
      <span className="readiness-dot" aria-hidden />
      <div className="readiness-row-body">
        <div className="readiness-row-top">
          <span className="readiness-label">{check.label}</span>
          <span className="readiness-status mono">{check.status}</span>
        </div>
        <div className="readiness-detail">{check.detail}</div>
      </div>
    </li>
  );
}
