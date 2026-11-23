import { fetchAuthSession } from "aws-amplify/auth";
import { config } from "./config";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function idToken(): Promise<string> {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  if (!token) throw new ApiError(401, "Not signed in");
  return token;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const base = config().apiUrl.replace(/\/$/, "");
  const res = await fetch(`${base}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Authorization: await idToken(),
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new ApiError(res.status, data.message ?? res.statusText);
  return data as T;
}

export async function putFile(url: string, file: File, contentType: string): Promise<void> {
  const res = await fetch(url, { method: "PUT", headers: { "Content-Type": contentType }, body: file });
  if (!res.ok) throw new ApiError(res.status, `Upload failed for ${file.name}`);
}

export async function userGroups(): Promise<string[]> {
  const session = await fetchAuthSession();
  const groups = session.tokens?.idToken?.payload["cognito:groups"];
  return Array.isArray(groups) ? groups.map(String) : [];
}
