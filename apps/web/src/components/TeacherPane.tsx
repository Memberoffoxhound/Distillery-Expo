import { useCallback, useEffect, useMemo, useState } from "react";
import type { DistilleryEvent } from "../types/events";
import {
  hasStageSignal,
  latestDecision,
  latestMetrics,
  latestStageStatus,
  progressOf,
  pct,
  stageDone,
  stageRunning,
} from "../lib/eventSelectors";
import {
  BIG_TEACHER_NAME,
  fetchTeachers,
  formatTeacherLabel,
  pullLiveTeacher,
  type TeacherInfo,
  type TeacherModel,
} from "../lib/api";
import { EmptyState } from "./EmptyState";

/**
 * Infer fixture vs live from teach events when API teacher list is thin.
 * Never silent about fixture. Never Chestnut.
 */
function teacherFromEvents(events: DistilleryEvent[]): Partial<TeacherInfo> {
  let fixtureHint = false;
  let liveHint = false;
  let modelName: string | null = null;
  let modelVersion: string | null = null;

  for (const ev of events) {
    if (ev.stage !== "teach") continue;
    const payload = (ev.payload ?? {}) as Record<string, unknown>;
    const meta = (payload.meta as Record<string, unknown> | undefined) ?? {};
    const msg = String(payload.message ?? payload.detail ?? "");
    if (
      payload.live === false ||
      meta.fixture === true ||
      meta.live === false ||
      /fixture|live=false/i.test(msg) ||
      (ev.kind === "decision" &&
        /fixture/i.test(String(payload.chosen ?? "")))
    ) {
      fixtureHint = true;
    }
    if (payload.live === true || meta.live === true) {
      liveHint = true;
    }
    const teacherMeta = meta.teacher ?? payload.teacher;
    if (typeof teacherMeta === "string" && teacherMeta.trim()) {
      modelName = teacherMeta;
    }
    if (typeof meta.model_name === "string") modelName = meta.model_name;
    if (typeof meta.model_version === "string") modelVersion = meta.model_version;
    if (typeof payload.model_name === "string") modelName = payload.model_name;
    if (typeof payload.model_version === "string")
      modelVersion = payload.model_version;
  }

  if (!fixtureHint && !liveHint && !modelName) return {};
  return {
    fixture: fixtureHint && !liveHint,
    live: liveHint && !fixtureHint,
    status: fixtureHint && !liveHint ? "fixture" : liveHint ? "live" : "unknown",
    source: fixtureHint && !liveHint ? "fixture" : liveHint ? "comma_master" : null,
    model_name: modelName,
    model_version: modelVersion,
  };
}

function mergeTeacher(
  api: TeacherInfo | null,
  fromEvents: Partial<TeacherInfo>
): TeacherInfo | null {
  if (!api && !Object.keys(fromEvents).length) return null;
  const base: TeacherInfo = { ...(api ?? {}), ...fromEvents };
  // Verified live artifact from API wins over stale event fixture hints
  if (api?.live === true || api?.teacher_artifact?.live === true) {
    base.fixture = false;
    base.live = true;
    base.status = "live";
    base.source = "comma_master";
  } else if (fromEvents.fixture) {
    // Events win on fixture honesty if they say fixture and API is not live
    base.fixture = true;
    base.live = false;
    base.status = "fixture";
    base.source = "fixture";
  }
  // Prefer API selected model name when events lack one
  if (!base.model_name && api?.selected?.name) {
    base.model_name = api.selected.name;
  }
  if (!base.model_version && api?.selected?.version) {
    base.model_version = api.selected.version;
  }
  return base;
}

/**
 * Teacher pane — binds to stage=teach progress / metric / stage / decision.
 * Selected teacher is locked to "comma master · big_driving_supercombo" when live.
 * Fixture is always labeled. One clear Pull live teacher control (POST /teachers/pull).
 * No Chestnut. No invented live GPU. Never offer small driving_supercombo.
 */
export function TeacherPane({ events }: { events: DistilleryEvent[] }) {
  const metrics = latestMetrics(events, "teach");
  const { fraction, detail } = progressOf(events, "teach");
  const stage = latestStageStatus(events, "teach");
  const decision = latestDecision(events, "teach");
  const signal = hasStageSignal(events, "teach");

  const shardDone = stageDone(events, "shard");
  const shardRunning = stageRunning(events, "shard");

  const [teacherApi, setTeacherApi] = useState<TeacherInfo | null>(null);
  const [teacherChecking, setTeacherChecking] = useState(true);
  const [pulling, setPulling] = useState(false);
  const [pullFrac, setPullFrac] = useState(0);
  const [pullDetail, setPullDetail] = useState<string | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);

  const refreshTeachers = useCallback(async () => {
    setTeacherChecking(true);
    try {
      const t = await fetchTeachers();
      setTeacherApi(t);
    } catch {
      setTeacherApi(null);
    } finally {
      setTeacherChecking(false);
    }
  }, []);

  useEffect(() => {
    void refreshTeachers();
  }, [refreshTeachers]);

  const onPullLive = useCallback(async () => {
    setPulling(true);
    setPullError(null);
    setPullFrac(0.02);
    setPullDetail(`Pulling comma master · ${BIG_TEACHER_NAME}…`);
    try {
      // Craig #24: POST /teachers/pull → teacher_pull job; progress on /ws/jobs/{id}
      const result = await pullLiveTeacher({
        onProgress: ({ fraction, detail }) => {
          if (Number.isFinite(fraction)) setPullFrac(Math.max(0, Math.min(1, fraction)));
          if (detail) setPullDetail(detail);
        },
      });
      const frac = Number(result.progress?.fraction ?? (result.live ? 1 : 0.5));
      setPullFrac(Number.isFinite(frac) ? frac : result.live ? 1 : 0.5);
      setPullDetail(
        result.progress?.detail ??
          result.label ??
          result.teacher_artifact?.detail ??
          (result.live
            ? `comma master · ${BIG_TEACHER_NAME} ready`
            : `Still fixture · ${BIG_TEACHER_NAME}`)
      );
      // Chip from refreshed GET /teachers (contract)
      setTeacherApi(result);
      if (!result.live) {
        setPullError(
          result.error ||
            result.teacher_artifact?.error ||
            result.teacher_artifact?.detail ||
            `Offline or download failed — staying fixture · ${BIG_TEACHER_NAME}`
        );
      } else {
        setPullError(null);
        setPullFrac(1);
      }
    } catch (e) {
      setPullError(
        e instanceof Error
          ? e.message
          : `Pull failed — staying fixture · ${BIG_TEACHER_NAME}`
      );
      setPullDetail(null);
      // Stay on last known teacher identity (fixture labeled)
      await refreshTeachers();
    } finally {
      setPulling(false);
    }
  }, [refreshTeachers]);

  const merged = useMemo(
    () => mergeTeacher(teacherApi, teacherFromEvents(events)),
    [teacherApi, events]
  );
  const label = useMemo(() => {
    if (teacherChecking && !merged) {
      return {
        primary: "Teacher · checking…",
        tone: "checking" as const,
        detail: "Loading teacher list/source…",
      };
    }
    return formatTeacherLabel(merged);
  }, [merged, teacherChecking]);

  const teacherList: TeacherModel[] = teacherApi?.teachers ?? [];
  const teacherRowLabel = (teacher: TeacherModel): string =>
    teacher.fixture || teacher.source === "fixture" || teacher.live === false
      ? `fixture · ${BIG_TEACHER_NAME}`
      : `comma master · ${BIG_TEACHER_NAME}`;

  const showPull =
    !pulling &&
    (label.tone === "fixture" ||
      label.tone === "unknown" ||
      label.tone === "checking" ||
      merged?.live !== true);

  const pullControls = (
    <div className="teacher-pull" aria-label="Pull live teacher">
      {(showPull || pulling) && (
        <button
          type="button"
          className="primary teacher-pull-btn"
          disabled={pulling}
          onClick={() => void onPullLive()}
          title={`POST /teachers/pull → teacher_pull job + /ws/jobs/<id> · ${BIG_TEACHER_NAME} only`}
        >
          {pulling ? "Pulling live teacher…" : "Pull live teacher"}
        </button>
      )}
      {(pulling || pullFrac > 0) && (
        <div className="teacher-pull-progress">
          <div className="bar-track" aria-hidden>
            <div
              className="bar-fill"
              style={{ width: `${Math.max(pulling ? 0.08 : 0, pullFrac) * 100}%` }}
            />
          </div>
          {pullDetail && <div className="teacher-pull-note muted">{pullDetail}</div>}
        </div>
      )}
      {pullError && !pulling && (
        <div className="teacher-pull-note is-error" role="status">
          {pullError}
        </div>
      )}
      {label.tone === "live" && !pulling && !pullError && (
        <div className="teacher-pull-note muted">
          Using live comma master · {BIG_TEACHER_NAME}
        </div>
      )}
    </div>
  );

  const identity = (
    <div
      className={`teacher-identity tone-${label.tone}`}
      title={label.detail}
      aria-label={label.primary}
    >
      <span className="teacher-identity-label">{label.primary}</span>
      {label.tone === "fixture" && (
        <span className="badge badge-fixture">fixture</span>
      )}
      {label.tone === "live" && (
        <span className="badge badge-live">live</span>
      )}
    </div>
  );

  if (!signal) {
    if (shardRunning) {
      return (
        <div className="stage-pane teacher-pane">
          {identity}
          {pullControls}
          <EmptyState
            title="Teacher standing by"
            body="Waiting for shard packing to finish. Soft-label pass starts only when teach events arrive on the bus."
            hint={`No live train-device claim invented while idle · teacher locked to comma master · ${BIG_TEACHER_NAME}`}
          />
        </div>
      );
    }
    if (shardDone) {
      return (
        <div className="stage-pane teacher-pane">
          {identity}
          {pullControls}
          <EmptyState
            title="Waiting to teach"
            body="Shards are ready. This pane stays quiet until the pipeline emits teach stage, progress, or metric events."
            hint={`Run demo / /jobs/teach · teacher locked to comma master · ${BIG_TEACHER_NAME}`}
          />
          {teacherList.length > 0 && (
            <div className="teacher-list" aria-label="Available teachers">
              {teacherList.map((t, i) => (
                <span key={String(t.id ?? t.name ?? i)} className="teacher-list-item mono">
                  {teacherRowLabel(t)}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    }
    return (
      <div className="stage-pane teacher-pane">
        {identity}
        {pullControls}
        <EmptyState
          title="Teacher standing by"
          body={
            label.tone === "fixture"
              ? "Fixture teacher path — soft-labels will be labeled offline, not comma master live. Pull live teacher when online."
              : `Teacher soft-labels from comma master · ${BIG_TEACHER_NAME} appear here when teach events stream on whatever tinygrad device is ready. Expo is mission control — not a live GPU dashboard.`
          }
          hint={`Teacher locked: comma master · ${BIG_TEACHER_NAME} when live · fixture · ${BIG_TEACHER_NAME} offline · no Chestnut`}
        />
        {teacherList.length > 0 && (
          <div className="teacher-list" aria-label="Available teachers">
            {teacherList.map((t, i) => (
              <span key={String(t.id ?? t.name ?? i)} className="teacher-list-item mono">
                {teacherRowLabel(t)}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }

  const status = stage?.status ?? (fraction >= 1 ? "done" : "running");
  const statusLabel =
    status === "done"
      ? "done"
      : status === "failed"
        ? "failed"
        : status === "running"
          ? "teaching"
          : status;
  const headline =
    stage?.detail ??
    (status === "done"
      ? "Soft labels ready"
      : status === "failed"
        ? "Teacher pass failed"
        : "Teacher soft-label pass");
  const showBar = status === "running" || status === "done" || fraction > 0;
  const barWidth = status === "done" ? 1 : fraction;

  return (
    <div className="stage-pane teacher-pane">
      {identity}
      {pullControls}
      <div className="stage-head">
        <div className="stage-title-row">
          <span className="stage-headline">{headline}</span>
          <span className={`stage-status ${status}`}>{statusLabel}</span>
        </div>
        {decision?.chosen ? (
          <div className="stage-decision muted">
            <span className="k">{decision.title}</span>
            <span className="v mono">{BIG_TEACHER_NAME}</span>
          </div>
        ) : (
          <div className="muted">{label.detail}</div>
        )}
      </div>

      {showBar && (
        <div className="stage-progress">
          <div className="bar-track" aria-hidden>
            <div className="bar-fill" style={{ width: `${barWidth * 100}%` }} />
          </div>
          <div className="stage-progress-meta">
            <span className="mono">{pct(barWidth)}</span>
            <span className="muted">
              {detail ??
                (status === "done"
                  ? "done"
                  : status === "running"
                    ? "labeling…"
                    : "—")}
            </span>
          </div>
        </div>
      )}

      {metrics.length > 0 ? (
        <div className="stage-metrics">
          {metrics.map(([k, { value, unit }]) => (
            <div key={k} className="metric-row">
              <span className="k">{k}</span>
              <span className="v">
                {Number.isFinite(value) && !Number.isInteger(value)
                  ? value.toFixed(1)
                  : value}
                {unit ? ` ${unit}` : ""}
              </span>
            </div>
          ))}
        </div>
      ) : status === "running" ? (
        <div className="muted">Awaiting teacher metrics…</div>
      ) : null}
    </div>
  );
}
