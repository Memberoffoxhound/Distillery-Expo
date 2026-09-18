/** Calm, specific empty / waiting copy — not demo one-liners. */

import type { ReactNode } from "react";

export function EmptyState({
  title,
  body,
  hint,
  actions,
}: {
  title: string;
  body?: string;
  hint?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="empty-state" role="status">
      <div className="empty-state-title">{title}</div>
      {body ? <p className="empty-state-body">{body}</p> : null}
      {hint ? <p className="empty-state-hint">{hint}</p> : null}
      {actions ? <div className="empty-state-actions">{actions}</div> : null}
    </div>
  );
}
