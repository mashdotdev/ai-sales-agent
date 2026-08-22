import { headers } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/server/auth";
import { fastapi } from "@/lib/fastapi";
import { getOrCreateWorkspace } from "@/lib/workspace";

/**
 * Proxies the dashboard's upload form to FastAPI. The browser never calls
 * FastAPI directly (see web/src/lib/fastapi.ts) — this route is session-
 * gated and injects the workspace id server-side so the client never needs
 * to know or supply it.
 */
export async function POST(req: NextRequest) {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const workspace = await getOrCreateWorkspace();
  const incoming = await req.formData();

  const forward = new FormData();
  forward.set("workspace_id", workspace.id);
  forward.set("title", incoming.get("title") ?? "");

  const text = incoming.get("text");
  if (typeof text === "string" && text.trim()) forward.set("text", text);

  const file = incoming.get("file");
  if (file instanceof File && file.size > 0) forward.set("file", file);

  const res = await fastapi("/knowledge/ingest", { method: "POST", body: forward });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
