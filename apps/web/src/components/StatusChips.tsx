import { useEffect, useState } from "react";
import {
  fetchStatusChipsSource,
  healthToStatusChips,
  type HealthResponse,
  type StatusChipModel,
} from "../lib/api";

/**
 * Calm mission-control chips: Train device + tinygrad.
 * Device-agnostic (GPU or CPU — never 7090-locked).
 * Never implies live GPU teach when backends are fixture.
 */
export function StatusChips() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setChecking(true);
    fetchStatusChipsSource()
      .then((h) => {
        if (!cancelled) setHealth(h);
      })
      .catch(() => {
        if (!cancelled) setHealth(null);
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const chips: StatusChipModel[] = healthToStatusChips(health, checking);

  return (
    <div className="status-chips" aria-label="Train device and tinygrad status">
      {chips.map((c) => (
        <span
          key={c.key}
          className={`sys-chip tone-${c.tone}`}
          title={c.title ?? `${c.label}: ${c.value}`}
        >
          <span className="sys-chip-label">{c.label}</span>
          <span className="sys-chip-value">{c.value}</span>
        </span>
      ))}
    </div>
  );
}
