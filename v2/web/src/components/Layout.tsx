import { Bell, ClipboardCheck, FilePlus2, Files, Inbox, LayoutDashboard, LogOut, UserRound } from "lucide-react";
import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";

export type Role = "provider" | "examiner";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
  end?: boolean;
}

const NAV: Record<Role, NavItem[]> = {
  provider: [
    { to: "/provider", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/provider/claims", label: "My Claims", icon: Files },
    { to: "/provider/new", label: "Submit a Claim", icon: FilePlus2 },
  ],
  examiner: [
    { to: "/examiner", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/examiner/reviews", label: "Review Queue", icon: Inbox, end: true },
    { to: "/examiner/reviews?status=APPROVED", label: "Decided Claims", icon: ClipboardCheck },
  ],
};

const DECIDED = new Set(["APPROVED", "DENIED", "PENDED_INFO_REQUESTED", "FAILED"]);

function isActive(path: string, search: string, to: string, end?: boolean): boolean {
  const [toPath, toQuery] = to.split("?");
  const status = new URLSearchParams(search).get("status") ?? "";
  if (toQuery) return path === toPath && DECIDED.has(status);
  if (toPath === "/examiner/reviews" && end) return path === toPath && !DECIDED.has(status);
  return end ? path === toPath : path.startsWith(toPath);
}

export function Logo() {
  return (
    <div className="logo">
      <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">
        <path d="M20 3 L34 9 V19 C34 28 28 34 20 37 C12 34 6 28 6 19 V9 Z" fill="none" stroke="var(--brand-600)" strokeWidth="3"
          strokeLinejoin="round" />
        <path d="M13 20 L18 25 L28 14" fill="none" stroke="var(--brand-500)" strokeWidth="3.2" strokeLinecap="round"
          strokeLinejoin="round" />
      </svg>
      <div>
        <strong>ClaimSense</strong>
        <small>Agentic claims review</small>
      </div>
    </div>
  );
}

function PromoArt() {
  return (
    <svg width="210" height="150" viewBox="0 0 210 150" aria-hidden="true">
      <ellipse cx="105" cy="142" rx="100" ry="8" fill="#ffffff" opacity="0.6" />
      <rect x="38" y="22" width="92" height="116" rx="8" fill="#ffffff" />
      <rect x="54" y="14" width="60" height="16" rx="6" fill="var(--brand-600)" />
      {[46, 62, 78, 94, 110].map((y, i) => (
        <g key={y}>
          <circle cx="58" cy={y + 4} r="5" fill={i < 3 ? "var(--brand-600)" : "#d5dbe6"} />
          <rect x="70" y={y} width={i % 2 ? 40 : 48} height="8" rx="4" fill="#dfe6f5" />
        </g>
      ))}
      <circle cx="146" cy="96" r="30" fill="none" stroke="#1d3d8f" strokeWidth="7" />
      <line x1="167" y1="118" x2="190" y2="140" stroke="#1d3d8f" strokeWidth="9" strokeLinecap="round" />
      <path d="M133 96 l9 9 l16 -18" fill="none" stroke="var(--brand-600)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M176 26 l4 9 l9 4 l-9 4 l-4 9 l-4 -9 l-9 -4 l9 -4 z" fill="#ffffff" />
    </svg>
  );
}

const PROMO: Record<Role, { title: string; text: string }> = {
  provider: { title: "Faster decisions on every claim", text: "Attach records with your claim form so AI review can verify each service." },
  examiner: { title: "Decide with the evidence in view", text: "Every AI finding cites the claim document or plan policy behind it." },
};

function useAttentionCount(role: Role) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => {
      const req =
        role === "examiner"
          ? api<{ reviews: unknown[] }>("/reviews?status=PENDING_REVIEW").then((r) => r.reviews.length)
          : api<{ claims: { status: string }[] }>("/claims").then(
              (r) => r.claims.filter((c) => ["PENDED_INFO_REQUESTED", "FAILED", "DENIED"].includes(c.status)).length,
            );
      req.then((n) => alive && setCount(n)).catch(() => undefined);
    };
    load();
    const t = window.setInterval(load, 60000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [role]);
  return count;
}

export function Shell({ role, email, signOut, children }: { role: Role; email?: string; signOut?: () => void; children: ReactNode }) {
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const attention = useAttentionCount(role);
  useEffect(() => {
    const close = (e: MouseEvent) => menuRef.current && !menuRef.current.contains(e.target as Node) && setMenu(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo />
        <nav className="nav" aria-label="Main">
          {NAV[role].map(({ to, label, icon: Icon, end }) => (
            <Link key={to} to={to} className={isActive(location.pathname, location.search, to, end) ? "active" : ""}>
              <Icon size={26} strokeWidth={1.5} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="promo">
          <h4>{PROMO[role].title}</h4>
          <p>{PROMO[role].text}</p>
          <PromoArt />
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button
            className="icon-btn"
            aria-label={role === "examiner" ? `${attention} claims awaiting review` : `${attention} claims need attention`}
            title={role === "examiner" ? "Claims awaiting review" : "Claims needing attention"}
            onClick={() => navigate(role === "examiner" ? "/examiner/reviews" : "/provider/claims")}
          >
            <Bell size={22} strokeWidth={1.75} />
            {attention > 0 && <span className="dot">{attention}</span>}
          </button>
          <div ref={menuRef} style={{ position: "relative" }}>
            <button className="icon-btn" aria-label="Account" aria-expanded={menu} onClick={() => setMenu(!menu)}>
              <UserRound size={22} strokeWidth={1.75} />
            </button>
            {menu && (
              <div className="menu" role="menu">
                <div className="who">
                  <div>{email}</div>
                  <span className="muted small">{role === "examiner" ? "Claims examiner" : "Medical provider"}</span>
                </div>
                <button className="btn quiet" role="menuitem" onClick={signOut}>
                  <LogOut size={16} /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>
        <main className="workspace">{children}</main>
      </div>
    </div>
  );
}
