import type { ReactNode } from "react";

export function Pane({
  title,
  tag,
  className,
  children,
}: {
  title: string;
  tag?: string;
  className: string;
  children: ReactNode;
}) {
  return (
    <section className={`pane ${className}`}>
      <div className="pane-title">
        <span>{title}</span>
        {tag ? <span className="tag">{tag}</span> : null}
      </div>
      <div className="pane-body">{children}</div>
    </section>
  );
}
