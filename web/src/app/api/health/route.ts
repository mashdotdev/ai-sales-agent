import { fastapi } from "@/lib/fastapi";

/**
 * Round-trips to FastAPI to prove the Next.js -> FastAPI boundary works,
 * both for the plain /health route and for the shared internal-secret
 * dependency (via /agent/draft, expected to 501 as an unimplemented stub
 * until Phase 4/6 — a 401 here would mean the secret doesn't match).
 */
export async function GET() {
  const backendUrl = process.env.FASTAPI_URL ?? "http://localhost:8000";

  try {
    const [healthRes, draftRes] = await Promise.all([
      fetch(`${backendUrl}/health`),
      fastapi("/agent/draft", { method: "POST" }),
    ]);

    const health = await healthRes.json();

    return Response.json({
      web: { status: "ok" },
      backend: { status: healthRes.ok ? "ok" : "error", ...health },
      internalSecretAuth: {
        status: draftRes.status === 501 ? "ok" : "unexpected",
        httpStatus: draftRes.status,
      },
    });
  } catch (err) {
    return Response.json(
      {
        web: { status: "ok" },
        backend: { status: "unreachable", error: String(err) },
      },
      { status: 503 },
    );
  }
}
