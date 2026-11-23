import type { ComponentType, ReactNode } from "react";

export function Card({ title, hint, right, children }: { title?: string; hint?: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {title && (
        <header className="card-head">
          <div className="tab">
            <h2>{title}</h2>
            {hint && <span className="hint">{hint}</span>}
          </div>
          <span className="spacer" />
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function SectionTitle({ icon: Icon, title, count }: { icon: ComponentType<{ size?: number; strokeWidth?: number }>; title: string; count?: string | number }) {
  return (
    <div className="section-title">
      <Icon size={30} strokeWidth={1.5} />
      <h3>{title}</h3>
      {count !== undefined && <span className="count">{count}</span>}
    </div>
  );
}

export function Empty({ icon: Icon, children }: { icon: ComponentType<{ size?: number; strokeWidth?: number }>; children: ReactNode }) {
  return (
    <div className="empty">
      <Icon size={44} strokeWidth={1.25} />
      <div>{children}</div>
    </div>
  );
}
