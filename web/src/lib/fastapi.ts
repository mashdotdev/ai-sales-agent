/**
 * Server-only fetch wrapper for calling the FastAPI backend.
 *
 * Next.js is the sole Google OAuth token authority and FastAPI is never
 * exposed to the browser (except the call WebSocket, authorized separately
 * by its own single-use token — see documents/plan.md). Every other request
 * to FastAPI is server-to-server and carries this shared secret.
 *
 * Import only from server components, route handlers, or Inngest functions —
 * never from client components (the secret must not reach the browser bundle).
 */

const FASTAPI_URL = process.env.FASTAPI_URL ?? "http://localhost:8010";
const INTERNAL_API_SECRET = process.env.INTERNAL_API_SECRET ?? "";

export async function fastapi(path: string, init: RequestInit = {}): Promise<Response> {
  if (!INTERNAL_API_SECRET) {
    throw new Error("INTERNAL_API_SECRET is not set in web/.env.local");
  }

  const headers = new Headers(init.headers);
  headers.set("X-Internal-Secret", INTERNAL_API_SECRET);
  // FormData bodies (file uploads) need `fetch` to set Content-Type itself,
  // multipart boundary included — setting it here would break the upload.
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  return fetch(`${FASTAPI_URL}${path}`, { ...init, headers });
}
