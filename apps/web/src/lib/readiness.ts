/**
 * Preflight for Start training — calm UI prompts, not CLI archaeology.
 * Tolerant of missing Craig fields; never invents live readiness.
 */

import {
  fetchDongle,
  fetchHealth,
  fetchRoutes,
  fetchTeachers,
  formatTeacherLabel,
  healthToStatusChips,
  type DongleInfo,
  type HealthResponse,
  type RouteSource,
  type TeacherInfo,
} from "./api";

export type ReadinessId =
  | "connect"
  | "mici_lan"
  | "hours"
  | "device"
  | "teacher";

export type CheckStatus = "ok" | "missing" | "unknown" | "fixture" | "shortfall";

export interface ReadinessCheck {
  id: ReadinessId;
  label: string;
  status: CheckStatus;
  detail: string;
  /** Short ask shown when not ok */
  ask?: string;
}

export interface ReadinessReport {
  checks: ReadinessCheck[];
  readyLive: boolean;
  /** Fixture path available as labeled fallback */
  fixtureOk: boolean;
  suggestedSource: RouteSource;
  dongle: DongleInfo | null;
  health: HealthResponse | null;
  teacher: TeacherInfo | null;
  hours: number | null;
  hoursKnown: boolean;
  minHours: number;
}

const MIN_HOURS = 50;

function hoursFromHealth(health: HealthResponse | null): {
  hours: number | null;
  known: boolean;
} {
  if (!health) return { hours: null, known: false };
  const raw =
    health.driving_hours ??
    health.route_hours ??
    health.total_hours ??
    health.hours ??
    (health as { hours_info?: { hours?: unknown; known?: unknown } }).hours_info
      ?.hours;
  const knownFlag = (health as { hours_known?: unknown }).hours_known;
  const info = (health as { hours_info?: { hours?: unknown; known?: unknown } })
    .hours_info;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return { hours: raw, known: knownFlag !== false && info?.known !== false };
  }
  if (info && typeof info.hours === "number") {
    return { hours: info.hours, known: info.known !== false };
  }
  return { hours: null, known: false };
}

export async function checkReadiness(): Promise<ReadinessReport> {
  let dongle: DongleInfo | null = null;
  let health: HealthResponse | null = null;
  let teacher: TeacherInfo | null = null;
  let lanRoutes = 0;
  let connectRoutes = 0;

  const results = await Promise.allSettled([
    fetchDongle(),
    fetchHealth(),
    fetchTeachers(),
    fetchRoutes("ssh", 5),
    fetchRoutes("connect", 5),
  ]);

  if (results[0].status === "fulfilled") dongle = results[0].value;
  if (results[1].status === "fulfilled") health = results[1].value;
  if (results[2].status === "fulfilled") teacher = results[2].value;
  if (results[3].status === "fulfilled") lanRoutes = results[3].value.routes.length;
  if (results[4].status === "fulfilled")
    connectRoutes = results[4].value.routes.length;

  const { hours, known: hoursKnown } = hoursFromHealth(health);
  const minHours = MIN_HOURS;

  // --- Connect ---
  const connectStatus = (dongle?.connect_status ?? "").toLowerCase();
  const needsJwt =
    connectStatus === "needs_jwt" ||
    connectStatus === "needs-jwt" ||
    (dongle != null && !dongle.connect_available);
  let connectCheck: ReadinessCheck;
  if (!dongle) {
    connectCheck = {
      id: "connect",
      label: "Connect",
      status: "unknown",
      detail: "Could not reach /dongle.",
      ask: "Is the API running? We’ll retry when you Start training again.",
    };
  } else if (needsJwt) {
    connectCheck = {
      id: "connect",
      label: "Connect",
      status: "missing",
      detail: "comma Connect needs a JWT.",
      ask: "Connect your comma account (JWT) — or use Find mici on LAN / ADB instead.",
    };
  } else if (dongle.connect_available || connectRoutes > 0) {
    connectCheck = {
      id: "connect",
      label: "Connect",
      status: "ok",
      detail:
        connectRoutes > 0
          ? `Connected · ${connectRoutes} route(s) listed`
          : "Connect available",
    };
  } else {
    connectCheck = {
      id: "connect",
      label: "Connect",
      status: "unknown",
      detail: "Connect status unclear.",
      ask: "Try Use Connect in Ingest, or Find mici on LAN.",
    };
  }

  // --- mici LAN (ADB + SSH) ---
  const adbOk =
    dongle?.adb_available === true ||
    ["found", "ready", "ok"].includes((dongle?.adb_status ?? "").toLowerCase());
  const devices = dongle?.devices ?? [];
  const lanDeviceCount = devices.filter((d) => {
    const k = String(d.kind ?? "").toLowerCase();
    return k === "adb" || k === "ssh" || k === "lan" || d.online !== false;
  }).length;
  let lanCheck: ReadinessCheck;
  if (lanRoutes > 0 || adbOk || dongle?.ssh_available || lanDeviceCount > 0) {
    lanCheck = {
      id: "mici_lan",
      label: "mici on LAN",
      status: "ok",
      detail:
        lanRoutes > 0
          ? `${lanRoutes} LAN route(s) via SSH/ADB`
          : adbOk
            ? "ADB path available — pick a found device in Ingest"
            : dongle?.ssh_available
              ? "SSH available — Find mici on LAN to list routes"
              : `${lanDeviceCount} device(s) reported`,
    };
  } else if (dongle?.force_fixture) {
    lanCheck = {
      id: "mici_lan",
      label: "mici on LAN",
      status: "fixture",
      detail: "Fixture forced — no live mici required for labeled offline path.",
      ask: "Live training needs a mici on LAN (ADB/SSH) or Connect.",
    };
  } else {
    lanCheck = {
      id: "mici_lan",
      label: "mici on LAN",
      status: "missing",
      detail: "No ADB/SSH device found yet.",
      ask: "Tap Find mici on LAN — pick a found ADB/SSH device. No manual IP dig.",
    };
  }

  // --- ≥50h driving data ---
  let hoursCheck: ReadinessCheck;
  if (hoursKnown && hours != null && hours >= minHours) {
    hoursCheck = {
      id: "hours",
      label: "Driving data",
      status: "ok",
      detail: `${hours.toFixed(1)} h ≥ ${minHours} h floor`,
    };
  } else if (hoursKnown && hours != null) {
    const short = Math.max(0, minHours - hours);
    hoursCheck = {
      id: "hours",
      label: "Driving data",
      status: "shortfall",
      detail: `${hours.toFixed(1)} h of ${minHours} h — short ${short.toFixed(1)} h`,
      ask: `Need about ${short.toFixed(1)} more hours of driving data before live train.`,
    };
  } else {
    hoursCheck = {
      id: "hours",
      label: "Driving data",
      status: "unknown",
      detail: `Hours not on /health yet (need ≥${minHours} h).`,
      ask: `Craig: expose driving_hours / hours_info on /health. Until then, fixture path is labeled offline.`,
    };
  }

  // --- Train device (tinygrad-compatible) ---
  const chips = healthToStatusChips(health, false);
  const deviceChip = chips.find((c) => c.key === "device");
  const tgChip = chips.find((c) => c.key === "tinygrad");
  let deviceCheck: ReadinessCheck;
  if (tgChip?.tone === "fixture" || deviceChip?.tone === "fixture") {
    deviceCheck = {
      id: "device",
      label: "Train device",
      status: "fixture",
      detail: `tinygrad ${tgChip?.value ?? "fixture"} · device ${deviceChip?.value ?? "fixture"}`,
      ask: "Fixture backends — live train needs a tinygrad-compatible device (GPU or CPU).",
    };
  } else if (
    tgChip?.tone === "ok" &&
    (deviceChip?.tone === "ok" || deviceChip?.value === "unknown")
  ) {
    // tinygrad ok; device may still be unknown until Craig lands fields
    const deviceUnknown = deviceChip?.value === "unknown";
    deviceCheck = {
      id: "device",
      label: "Train device",
      status: deviceUnknown ? "unknown" : "ok",
      detail: `tinygrad ${tgChip.value} · ${deviceChip?.value ?? "unknown"}`,
      ask: deviceUnknown
        ? "tinygrad looks ok; device name pending on /health (device_name / device_status)."
        : undefined,
    };
  } else if (tgChip?.tone === "warn" || tgChip?.value === "missing") {
    deviceCheck = {
      id: "device",
      label: "Train device",
      status: "missing",
      detail: "tinygrad missing",
      ask: "Install / expose tinygrad on this machine, then retry.",
    };
  } else {
    deviceCheck = {
      id: "device",
      label: "Train device",
      status: "unknown",
      detail: deviceChip
        ? `${deviceChip.value} · tinygrad ${tgChip?.value ?? "?"}`
        : "Checking…",
      ask: "Waiting on /health device + tinygrad fields from Craig.",
    };
  }

  // --- Teacher (comma master) ---
  const tLabel = formatTeacherLabel(teacher);
  let teacherCheck: ReadinessCheck;
  if (tLabel.tone === "live") {
    teacherCheck = {
      id: "teacher",
      label: "Teacher",
      status: "ok",
      detail: tLabel.primary,
    };
  } else if (tLabel.tone === "fixture") {
    teacherCheck = {
      id: "teacher",
      label: "Teacher",
      status: "fixture",
      detail: tLabel.primary,
      ask: "Fixture teacher — live path needs comma master · <model> from /teachers.",
    };
  } else {
    teacherCheck = {
      id: "teacher",
      label: "Teacher",
      status: "unknown",
      detail: tLabel.primary,
      ask: "Select comma-master teacher when the list lands (GET /teachers). No Chestnut.",
    };
  }

  const checks = [connectCheck, lanCheck, hoursCheck, deviceCheck, teacherCheck];

  // Live ready only when Connect/LAN, ≥50h, device, and comma-master teacher all ok
  const miciOk =
    connectCheck.status === "ok" || lanCheck.status === "ok";
  const readyLiveStrict =
    miciOk &&
    hoursCheck.status === "ok" &&
    deviceCheck.status === "ok" &&
    teacherCheck.status === "ok";

  const suggestedSource: RouteSource =
    lanCheck.status === "ok" && lanRoutes > 0
      ? "ssh"
      : connectCheck.status === "ok"
        ? "connect"
        : "fixture";

  return {
    checks,
    readyLive: readyLiveStrict,
    fixtureOk: true,
    suggestedSource,
    dongle,
    health,
    teacher,
    hours,
    hoursKnown,
    minHours,
  };
}
