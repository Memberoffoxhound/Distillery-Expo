/** Calm, specific empty / waiting copy — not demo one-liners. */

export function EmptyState({
  title,
  body,
  hint,
}: {
  title: string;
  body?: string;
  hint?: string;
}) {
  return (
    <div className="empty-state" role="status">
      <div className="empty-state-title">{title}</div>
      {body ? <p className="empty-state-body">{body}</p> : null}
      {hint ? <p className="empty-state-hint">{hint}</p> : null}
    </div>
  );
}
