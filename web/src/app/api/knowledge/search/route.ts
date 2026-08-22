import { headers } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/server/auth";
import { fastapi } from "@/lib/fastapi";

/** Thin proxy for the dashboard's search box — see api/knowledge/ingest/route.ts. */
export async function GET(req: NextRequest) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { searchParams } = new URL(req.url);
  const q = searchParams.get("q") ?? "";
  const topK = searchParams.get("top_k") ?? "5";

  const res = await fastapi(`/knowledge/search?q=${encodeURIComponent(q)}&top_k=${encodeURIComponent(topK)}`);
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
