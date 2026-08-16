"use client";

import { signOut, requestGoogleWorkspaceAccess } from "@/lib/auth-client";
import { useRouter } from "next/navigation";

export function DashboardShell({
  userName,
  hasGoogleWorkspace,
}: {
  userName: string;
  hasGoogleWorkspace: boolean;
}) {
  const router = useRouter();

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 px-4 py-12">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">AI Sales Employee</h1>
          <p className="text-sm text-foreground/60">Welcome, {userName}</p>
        </div>
        <button
          className="rounded border px-3 py-1.5 text-sm"
          onClick={async () => {
            await signOut();
            router.push("/sign-in");
          }}
        >
          Sign out
        </button>
      </header>

      <section className="rounded border p-4">
        <h2 className="font-medium">Google Workspace</h2>
        <p className="mt-1 text-sm text-foreground/60">
          Gmail + Calendar access for sending, receiving, and booking on your behalf.
        </p>
        <div className="mt-3 flex items-center gap-3">
          <span
            className={`h-2 w-2 rounded-full ${hasGoogleWorkspace ? "bg-green-500" : "bg-foreground/30"}`}
          />
          <span className="text-sm">{hasGoogleWorkspace ? "Connected" : "Not connected"}</span>
          {!hasGoogleWorkspace && (
            <button
              className="ml-auto rounded bg-foreground px-3 py-1.5 text-sm text-background"
              onClick={() => requestGoogleWorkspaceAccess()}
            >
              Connect Google Workspace
            </button>
          )}
        </div>
      </section>

      <section className="rounded border border-dashed p-4 text-sm text-foreground/60">
        Knowledge base, leads, campaigns, and calls land here in later phases —
        this is the Phase 1 shell, just enough to exercise sign-up, sign-in,
        and the Google Workspace connect flow end to end.
      </section>
    </main>
  );
}
