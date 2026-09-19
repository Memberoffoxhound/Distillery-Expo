import { useEffect, useState } from "react";
import {
  fetchStatusChipsSource,
  healthToStatusChips,
  type HealthResponse,
  type StatusChipModel,
} from "../lib/api";

/**
 * Calm mission-control chips: PyTorch readiness + train device.
 * Device-agnostic (CUDA, ROCm, MPS, or CPU — never 7090-locked).
 * These chips describe the torch runtime only; teacher backend is separate.
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
    <div className="status-chips" aria-label="PyTorch train device status">
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
