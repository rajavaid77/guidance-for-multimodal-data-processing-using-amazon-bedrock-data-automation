export interface SiteConfig {
  region: string;
  userPoolId: string;
  userPoolClientId: string;
  apiUrl: string;
}

let current: SiteConfig | null = null;

/** config.json is written by the CDK deployment (public identifiers only, no secrets). */
export async function loadConfig(): Promise<SiteConfig> {
  const res = await fetch("/config.json", { cache: "no-store" });
  if (!res.ok) throw new Error("Missing config.json");
  current = (await res.json()) as SiteConfig;
  return current;
}

export function config(): SiteConfig {
  if (!current) throw new Error("Config not loaded");
  return current;
}
