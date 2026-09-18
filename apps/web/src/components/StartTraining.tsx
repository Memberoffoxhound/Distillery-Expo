import { useCallback, useState } from "react";
import {
  checkReadiness,
  type ReadinessCheck,
  type ReadinessReport,
} from "../lib/readiness";
import type { RouteSource } from "../lib/api";

/**
 * Primary simple-user action: Start training.
 * Preflight via GET /ready gaps; start via POST /jobs/train_all (never auto-flash).
 * Fixture path always labeled — DISTILLERY_ALLOW_TOY_TRAIN still not licensed.
 */
export function StartTraining({
  busy,
  onStart,
}: {
  busy: boolean;
  onStart: (opts: {
    source: RouteSource;
    forceFixture?: boolean;
    allowToy?: boolean;
  }) => void | Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runCheck = useCallback(async (forceFixture = false) => {
    setChecking(true);
    setError(null);
    setOpen(true);
    try {
      const r = await checkReadiness({ force_fixture: forceFixture });
      setReport(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "GET /ready failed");
      setReport(null);
    } finally {
      setChecking(false);
    }
  }, []);

  const startLive = () => {
    if (!report) return;
    void onStart({
      source:
        report.suggestedSource === "fixture" ? "auto" : report.suggestedSource,
      forceFixture: false,
    });
    setOpen(false);
  };

  const startFixture = () => {
    void onStart({ source: "fixture", forceFixture: true });
    setOpen(false);
  };

  const missing = report?.checks.filter((c) => c.status !== "ok") ?? [];

  return (
    <div className="start-training-wrap">
      <button
        className="primary start-training-btn"
        disabled={busy || checking}
        onClick={() => void runCheck(false)}
        title="GET /ready then POST /jobs/train_all — never auto-flashes"
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
                Live gaps from GET /ready. train_all runs ingest→…→eval — never
                auto-flashes. Toy override still not licensed.
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
            <div className="muted">Checking GET /ready gaps…</div>
          )}

          {report && (
            <>
              <ul className="readiness-list">
                {report.checks.map((c) => (
                  <ReadinessRow key={`${c.id}-${c.code ?? ""}`} check={c} />
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
                        <li key={`${c.id}-${c.code ?? ""}`}>
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
                    title="POST /jobs/train_all"
                  >
                    Start live training
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={startLive}
                    title="POST /jobs/train_all — may 409 with gaps"
                  >
                    Try anyway
                  </button>
                )}
                <button
                  className="fixture-btn"
                  disabled={busy}
                  onClick={startFixture}
                  title="POST /jobs/train_all {source:fixture, force_fixture:true} — labeled offline"
                >
                  Start fixture (labeled)
                </button>
                <button
                  type="button"
                  disabled={checking}
                  onClick={() => void runCheck(false)}
                >
                  Recheck
                </button>
              </div>
              <p className="readiness-footnote muted">
                Fixture / DISTILLERY_ALLOW_TOY_TRAIN=1 is always labeled offline
                and not licensed. Flash never auto-writes.
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
