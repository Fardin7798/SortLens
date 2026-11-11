// The ONLY place that knows the backend address.
export const API_BASE = process.env.NEXT_PUBLIC_SORTLENS_API ?? "http://127.0.0.1:8765";

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export type Health = { status: string; version: string };
