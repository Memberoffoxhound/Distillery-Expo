import { useCallback, useEffect, useState } from "react";
import {
  fetchFocus,
  submitFocus,
  type FocusHistoryEntry,
  type FocusState,
} from "../lib/api";

/**
 * Calm focus coach UI — plain English → training focus.
 * Binds GET/POST /focus (thin stub until Graig deepens LLM coach).
 */
export function FocusPane({
  onFocusChange,
}: {
  onFocusChange?: (focus: string | null) => void;
}) {
  const [text, setText] = useState("");
  const [current, setCurrent] = useState<string | null>(null);
  const [history, setHistory] = useState<FocusHistoryEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const apply = useCallback(
    (state: FocusState, seedInput = false) => {
      setCurrent(state.focus);
      setHistory(state.history ?? []);
      onFocusChange?.(state.focus);
      if (seedInput && state.focus) setText(state.focus);
    },
    [onFocusChange]
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const state = await fetchFocus();
        if (!cancelled) {
          apply(state, true);
          setLoaded(true);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "GET /focus failed");
          setLoaded(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apply]);

  const onSubmit = async () => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const state = await submitFocus(trimmed);
      apply(state);
    } catch (e) {
      setError(e instanceof Error ? e.message : "POST /focus failed");
    } finally {
      setBusy(false);
    }
  };

  const reuse = (entry: FocusHistoryEntry) => {
    setText(entry.text);
  };

  return (
    <div className="focus-pane">
      <div className="focus-prompt">What should we get better at?</div>
      <textarea
        className="focus-input"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="stop lights, stop signs, cut-ins"
        aria-label="Training focus"
        disabled={busy}
      />
      <div className="focus-actions">
        <button
          type="button"
          className="primary focus-submit"
          disabled={busy || !text.trim()}
          onClick={() => void onSubmit()}
          title="POST /focus — store coach focus"
        >
          {busy ? "Saving…" : "Submit focus"}
        </button>
        {current && (
          <span className="focus-current muted" title="Current coach focus">
            Active · {current}
          </span>
        )}
      </div>
      {error && <div className="ingest-error">{error}</div>}
      {loaded && history.length > 0 && (
        <div className="focus-history" aria-label="Focus history">
          {history.map((h) => (
            <button
              key={h.id}
              type="button"
              className={`focus-chip${h.text === current ? " active" : ""}`}
              onClick={() => reuse(h)}
              title={h.ts}
            >
              {h.text}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
