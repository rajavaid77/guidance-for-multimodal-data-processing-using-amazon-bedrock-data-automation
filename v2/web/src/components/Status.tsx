import { CircleAlert, CircleCheck, CircleX, Clock, Hourglass, Info, LoaderCircle, TriangleAlert } from "lucide-react";
import type { ComponentType } from "react";

type Tone = "good" | "warn" | "bad" | "info" | "neutral";
interface Look {
  tone: Tone;
  label: string;
  Icon: ComponentType<{ size?: number }>;
}

const LOOKS: Record<string, Look> = {
  DRAFT: { tone: "neutral", label: "Draft", Icon: Clock },
  SUBMITTED: { tone: "info", label: "Submitted", Icon: LoaderCircle },
  EXTRACTING: { tone: "info", label: "Reading documents", Icon: LoaderCircle },
  AGENT_REVIEW: { tone: "info", label: "AI review", Icon: LoaderCircle },
  PENDING_REVIEW: { tone: "warn", label: "Awaiting examiner", Icon: Hourglass },
  FINALIZING: { tone: "info", label: "Finalizing", Icon: LoaderCircle },
  APPROVED: { tone: "good", label: "Approved", Icon: CircleCheck },
  DENIED: { tone: "bad", label: "Denied", Icon: CircleX },
  PENDED_INFO_REQUESTED: { tone: "warn", label: "Info requested", Icon: CircleAlert },
  FAILED: { tone: "bad", label: "Failed", Icon: TriangleAlert },
  APPROVE: { tone: "good", label: "Approve", Icon: CircleCheck },
  DENY: { tone: "bad", label: "Deny", Icon: CircleX },
  PEND: { tone: "warn", label: "Pend", Icon: CircleAlert },
  ERROR: { tone: "bad", label: "Error", Icon: CircleX },
  WARNING: { tone: "warn", label: "Warning", Icon: TriangleAlert },
  INFO: { tone: "neutral", label: "Info", Icon: Info },
};

/** Status is always icon + label, never colour alone. */
export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  const look = LOOKS[value] ?? { tone: "neutral" as Tone, label: value.replaceAll("_", " ").toLowerCase(), Icon: Info };
  return (
    <span className={`pill ${look.tone}`}>
      <look.Icon size={13} />
      {look.label}
    </span>
  );
}

export function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`pill ${ok ? "good" : "bad"}`}>
      {ok ? <CircleCheck size={13} /> : <CircleX size={13} />}
      {label} {ok ? "passed" : "failed"}
    </span>
  );
}

export const money = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const when = (v: string | null | undefined) =>
  v ? new Date(v.replace(" ", "T") + (v.includes("T") || v.endsWith("Z") ? "" : "Z")).toLocaleString() : "—";

export const shortId = (id: string) => `${id.slice(0, 12)}…`;

export const PROCESSING = new Set(["SUBMITTED", "EXTRACTING", "AGENT_REVIEW", "FINALIZING"]);
export const FINAL = new Set(["APPROVED", "DENIED", "PENDED_INFO_REQUESTED"]);
