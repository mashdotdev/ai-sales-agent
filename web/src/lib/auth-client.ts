import { createAuthClient } from "better-auth/react";

export const authClient = createAuthClient({
  baseURL: process.env.NEXT_PUBLIC_APP_URL,
});

export const { signIn, signUp, signOut, useSession } = authClient;

// The Gmail + Calendar scopes the SDR needs (send/read/modify mail, manage
// events, check freebusy). Requested here, separately from login, so plain
// sign-in stays a low-scope one-click consent — see boundary rule 2 and the
// Phase 1 note in documents/plan.md.
const GOOGLE_WORKSPACE_SCOPES = [
  "https://www.googleapis.com/auth/gmail.send",
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.modify",
  "https://www.googleapis.com/auth/calendar.events",
  "https://www.googleapis.com/auth/calendar.freebusy",
];

/** Call from a "Connect Google Workspace" button, not at signup. */
export async function requestGoogleWorkspaceAccess() {
  await authClient.linkSocial({
    provider: "google",
    scopes: GOOGLE_WORKSPACE_SCOPES,
  });
}
