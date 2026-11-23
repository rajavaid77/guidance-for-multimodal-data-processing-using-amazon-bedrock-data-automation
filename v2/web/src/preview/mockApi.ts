// Fixture-backed stand-in for ../api used only by the dev preview (vite.preview.config.ts).
const files = import.meta.glob("/preview-fixtures/*.json", { eager: true, import: "default" }) as Record<string, unknown>;
const fx = (name: string) => files[`/preview-fixtures/${name}.json`] ?? {};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Batch stages advance on each claim GET so the live refresh is visible.
const STAGES = ["EXTRACTING", "WAITING", "MERGING", "AGENT_REVIEW", "DONE"];
let gets = 0;
let uploaded = false;
let rerunReason: string | null = null;
function reviewWithRuns(name: string) {
  const base = fx(name) as { claim?: { status?: string }; runs?: unknown[]; current_run?: number; can_rerun?: boolean };
  if (!rerunReason) return base;
  const runs = [...(base.runs ?? []), { run_id: 2, mode: "AGENT", requested_by: "preview", requested_at: new Date().toISOString(), reason: rerunReason, outcome: "AGENT_REVIEW", agent_decision: null, agent_confidence: null, final_decision: null }];
  return { ...base, claim: { ...base.claim, status: "AGENT_REVIEW" }, runs, current_run: 2, can_rerun: false };
}

function claimWithProgress() {
  const base = fx("claim_S5") as { documents: Record<string, unknown>[]; batches: { stage: string; [k: string]: unknown }[] };
  const stage = STAGES[Math.min(Math.floor(gets++ / 2), STAGES.length - 1)];
  const done = stage === "DONE";
  const documents = base.documents.map((d) => (d.status === "PROCESSING" && done ? { ...d, status: "READY", part_id: 6, name: "Addendum note" } : d));
  const batches: Record<string, unknown>[] = base.batches.map((b) => ({ ...b, stage }));
  if (uploaded) batches.unshift({ ...base.batches[0], batch_id: "BATCH-" + "b".repeat(32), stage: "QUEUED", document_count: 2 });
  return { ...base, documents, batches };
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  await new Promise((r) => setTimeout(r, 150));
  if (init.method === "POST") {
    if (path === "/claims") return { claim_id: "CLM-preview", uploads: [] } as T;
    if (/^\/claims\/[^/]+\/batches$/.test(path)) {
      const n = ((init.body as { documents?: unknown[] })?.documents ?? []).length;
      return { claim_id: "CLM-preview", batch_id: "BATCH-" + "b".repeat(32), uploads: Array.from({ length: n }, () => ({ key: "k", upload_url: "u", content_type: "application/pdf" })), expires_in: 300 } as T;
    }
    if (/\/batches\/[^/]+\/submit$/.test(path)) {
      uploaded = true;
      return { stage: "QUEUED" } as T;
    }
    if (/^\/reviews\/[^/]+\/rerun$/.test(path)) {
      rerunReason = String((init.body as { reason?: string })?.reason ?? "");
      return { run_id: 2, mode: "AGENT", status: "AGENT_REVIEW" } as T;
    }
    return {} as T;
  }
  const url = new URL(path, "http://x");
  if (url.pathname === "/claims") return fx("claims") as T;
  if (/^\/claims\/[^/]+\/parts\/[^/]+\/url$/.test(url.pathname)) return fx("claim_part_url") as T;
  if (url.pathname.startsWith("/claims/")) return claimWithProgress() as T;
  if (url.pathname === "/reviews") return fx(`reviews_${url.searchParams.get("status") ?? "PENDING_REVIEW"}`) as T;
  if (url.pathname.startsWith("/reviews/")) return reviewWithRuns(url.pathname.includes("1760121b") ? "review_S5" : "review_S4") as T;
  throw new ApiError(404, `No fixture for ${path}`);
}

export async function putFile(): Promise<void> {}

export async function userGroups(): Promise<string[]> {
  return [new URLSearchParams(location.search).get("role") === "examiner" ? "examiners" : "providers"];
}
