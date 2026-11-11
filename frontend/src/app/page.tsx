"use client";

import { useEffect, useState } from "react";

import { getJson, type Health } from "@/lib/api";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<Health>("/api/health")
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <main className="mx-auto max-w-2xl p-8 font-sans">
      <h1 className="text-3xl font-bold">SortLens</h1>
      <p className="mt-2 text-gray-600">
        Local photo organizer. Categorizes only, never deletes on its own.
      </p>
      <div className="mt-6 rounded-lg border p-4">
        <span className="font-medium">Backend: </span>
        {health ? `connected (v${health.version})` : error ? `not reachable (${error})` : "checking…"}
      </div>
    </main>
  );
}
