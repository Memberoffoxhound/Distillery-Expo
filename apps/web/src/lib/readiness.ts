/**
 * Preflight for Start training — binds to live GET /ready gaps.
 * Calm UI prompts from Craig structured gaps; no client-side stub readiness.
 */

import {
  fetchReady,
  BIG_TEACHER_NAME,
  fetchTeachers,
  formatTeacherLabel,
  type ReadyGap,
  type ReadyResponse,
  type RouteSource,
  type TeacherInfo,
} from "./api";

export type ReadinessId =
  | "connect"
  | "mici_lan"
  | "hours"
  | "device"
  | "teacher"
  | "other";

export type CheckStatus = "ok" | "missing" | "unknown" | "fixture" | "shortfall";

export interface ReadinessCheck {
  id: ReadinessId;
  label: string;
  status: CheckStatus;
  detail: string;
  ask?: string;
  code?: string;
}

export interface ReadinessReport {
  checks: ReadinessCheck[];
  readyLive: boolean;
  fixtureOk: boolean;
  suggestedSource: RouteSource;
  ready: ReadyResponse | null;
  teacher: TeacherInfo | null;
  gaps: ReadyGap[];
  hours: number | null;
  hoursKnown: boolean;
  minHours: number;
}

const GAP_META: Record<
  string,
  { id: ReadinessId; label: string; ask: string }
> = {
  insufficient_hours: {
    id: "hours",
    label: "Driving data",
    ask: "Need ≥50h driving data (or DISTILLERY_ALLOW_TOY_TRAIN=1 for CI — still not licensed).",
  },
  device_not_ready: {
    id: "device",
    label: "Train device",
    ask: "Install / expose PyTorch on a CUDA, ROCm, MPS, or CPU device, then retry.",
  },
  teacher_not_selected: {
    id: "teacher",
    label: "Teacher",
    ask: `Select comma master · ${BIG_TEACHER_NAME} (GET /teachers). No Chestnut.`,
  },
  mici_not_found: {
    id: "mici_lan",
    label: "mici on LAN",
    ask: "Tap Find mici on LAN — pick a found ADB/SSH device.",
  },
  connect_not_configured: {
    id: "connect",
    label: "Connect",
    ask: "Connect your comma account (JWT via Use Connect) — or use Find mici on LAN / fixture.",
  },
  discover_error: {
    id: "mici_lan",
    label: "Discover",
    ask: "Discovery failed — is the API running?",
  },
};

function gapToCheck(gap: ReadyGap): ReadinessCheck {
  const meta = GAP_META[gap.code] ?? {
    id: "other" as ReadinessId,
    label: gap.code,
    ask: gap.message,
  };
  const status: CheckStatus =
    gap.code === "insufficient_hours" ? "shortfall" : "missing";
  return {
    id: meta.id,
    label: meta.label,
    status,
    detail:
      gap.code === "teacher_not_selected"
        ? `Teacher target is comma master · ${BIG_TEACHER_NAME}; select it before training.`
        : gap.message,
    ask: meta.ask,
    code: gap.code,
  };
}

function okCheck(
  id: ReadinessId,
  label: string,
  detail: string
): ReadinessCheck {
  return { id, label, status: "ok", detail };
}

/**
 * Live readiness from GET /ready (+ locked big teacher label from GET /teachers).
 */
export async function checkReadiness(opts?: {
  force_fixture?: boolean;
  allow_toy?: boolean;
}): Promise<ReadinessReport> {
  const force_fixture = opts?.force_fixture ?? false;
  const allow_toy = opts?.allow_toy ?? false;

  const [readySettled, teacherSettled] = await Promise.allSettled([
    fetchReady({ force_fixture, allow_toy }),
    fetchTeachers(),
  ]);

  if (readySettled.status === "rejected") {
    throw readySettled.reason instanceof Error
      ? readySettled.reason
      : new Error("GET /ready failed");
  }

  const ready = readySettled.value;
  const teacher =
    teacherSettled.status === "fulfilled" ? teacherSettled.value : null;

  const gaps = Array.isArray(ready.gaps) ? ready.gaps : [];
  const byCode = new Set(gaps.map((g) => g.code));

  const checks: ReadinessCheck[] = [];

  // Always show the five calm rows; fill from gaps or ok.
  if (byCode.has("connect_not_configured")) {
    checks.push(gapToCheck(gaps.find((g) => g.code === "connect_not_configured")!));
  } else {
    checks.push(okCheck("connect", "Connect", "Connect JWT ok or not required for this path"));
  }

  if (byCode.has("mici_not_found") || byCode.has("discover_error")) {
    const g =
      gaps.find((g) => g.code === "mici_not_found") ??
      gaps.find((g) => g.code === "discover_error")!;
    checks.push(gapToCheck(g));
  } else {
    checks.push(okCheck("mici_lan", "mici on LAN", "ADB/SSH path available or fixture path"));
  }

  if (byCode.has("insufficient_hours")) {
    checks.push(gapToCheck(gaps.find((g) => g.code === "insufficient_hours")!));
  } else {
    const hours = ready.hours as { hours?: number; known?: boolean } | null;
    const h = typeof hours?.hours === "number" ? hours.hours : null;
    const floor = ready.min_train_hours ?? 50;
    checks.push(
      okCheck(
        "hours",
        "Driving data",
        h != null ? `${h} h ≥ ${floor} h floor` : `Hours gate ok (≥${floor} h)`
      )
    );
  }

  if (byCode.has("device_not_ready")) {
    checks.push(gapToCheck(gaps.find((g) => g.code === "device_not_ready")!));
  } else {
    const probe = (ready.probe ?? ready.device) as Record<string, unknown> | null;
    const name = probe && typeof probe.device_name === "string" ? probe.device_name : null;
    const kind = probe && typeof probe.device_kind === "string" ? probe.device_kind : null;
    checks.push(
      okCheck(
        "device",
        "Train device",
        [name, kind].filter(Boolean).join(" · ") || "torch device ready"
      )
    );
  }

  if (byCode.has("teacher_not_selected")) {
    checks.push(gapToCheck(gaps.find((g) => g.code === "teacher_not_selected")!));
  } else {
    const tLabel = formatTeacherLabel(teacher);
    const fromReady = ready.teacher as { name?: string; source?: string } | null;
    checks.push(
      okCheck(
        "teacher",
        "Teacher",
        tLabel.primary !== "Teacher · unknown"
          ? tLabel.primary
          : fromReady?.name
            ? `${fromReady.source === "fixture" ? "fixture" : "comma master"} · ${BIG_TEACHER_NAME}`
            : `Teacher target: comma master · ${BIG_TEACHER_NAME}`
      )
    );
  }

  // Any other gaps
  for (const g of gaps) {
    if (
      ![
        "connect_not_configured",
        "mici_not_found",
        "discover_error",
        "insufficient_hours",
        "device_not_ready",
        "teacher_not_selected",
      ].includes(g.code)
    ) {
      checks.push(gapToCheck(g));
    }
  }

  const hoursObj = ready.hours as { hours?: number; known?: boolean } | null;
  const hours =
    typeof hoursObj?.hours === "number" ? hoursObj.hours : null;
  const hoursKnown = hoursObj?.known === true || hours != null;

  const readyLive = ready.ok === true && gaps.length === 0 && !force_fixture;
  const suggestedSource: RouteSource = force_fixture
    ? "fixture"
    : byCode.has("mici_not_found")
      ? byCode.has("connect_not_configured")
        ? "fixture"
        : "connect"
      : "auto";

  return {
    checks,
    readyLive,
    fixtureOk: true,
    suggestedSource,
    ready,
    teacher,
    gaps,
    hours,
    hoursKnown,
    minHours: ready.min_train_hours ?? 50,
  };
}
