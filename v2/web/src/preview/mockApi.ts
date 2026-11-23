// Fixture-backed stand-in for ../api used only by the dev preview (vite.preview.config.ts).
const files = import.meta.glob("/preview-fixtures/*.json", { eager: true, import: "default" }) as Record<string, unknown>;
const fx = (name: string) => files[`/preview-fixtures/${name}.json`] ?? {};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  await new Promise((r) => setTimeout(r, 150));
  if (init.method === "POST") {
    if (path === "/claims") return { claim_id: "CLM-preview", uploads: [] } as T;
    return {} as T;
  }
  const url = new URL(path, "http://x");
  if (url.pathname === "/claims") return fx("claims") as T;
  if (url.pathname.startsWith("/claims/")) return fx("claim_S5") as T;
  if (url.pathname === "/reviews") return fx(`reviews_${url.searchParams.get("status") ?? "PENDING_REVIEW"}`) as T;
  if (url.pathname.startsWith("/reviews/")) return fx(url.pathname.includes("1760121b") ? "review_S5" : "review_S4") as T;
  throw new ApiError(404, `No fixture for ${path}`);
}

export async function putFile(): Promise<void> {}

export async function userGroups(): Promise<string[]> {
  return [new URLSearchParams(location.search).get("role") === "examiner" ? "examiners" : "providers"];
}
