import { betterAuth } from "better-auth";
import { prismaAdapter } from "better-auth/adapters/prisma";
import { Resend } from "resend";
import { prisma } from "@/lib/prisma";

// Pattern mirrors saas-starter-kit/apps/web/src/server/auth.ts almost
// verbatim (prismaAdapter + Resend handlers) — only the Google provider
// config differs, per boundary rule 2 in documents/plan.md.

function getResend() {
  return new Resend(process.env.RESEND_API_KEY ?? "placeholder");
}

export const auth = betterAuth({
  database: prismaAdapter(prisma, {
    provider: "postgresql",
  }),
  baseURL: process.env.BETTER_AUTH_URL ?? process.env.NEXT_PUBLIC_APP_URL,
  secret: process.env.BETTER_AUTH_SECRET,
  emailAndPassword: {
    enabled: true,
    requireEmailVerification: true,
    sendResetPassword: async ({ user, url }) => {
      await getResend().emails.send({
        from: process.env.RESEND_FROM_EMAIL ?? "onboarding@resend.dev",
        to: user.email,
        subject: "Reset your password",
        html: `<p>Click <a href="${url}">here</a> to reset your password.</p>`,
      });
    },
  },
  emailVerification: {
    sendVerificationEmail: async ({ user, url }) => {
      await getResend().emails.send({
        from: process.env.RESEND_FROM_EMAIL ?? "onboarding@resend.dev",
        to: user.email,
        subject: "Verify your email",
        html: `<p>Click <a href="${url}">here</a> to verify your email address.</p>`,
      });
    },
    sendOnSignUp: true,
  },
  socialProviders: {
    google: {
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
      // accessType/prompt so Google actually issues a refresh token — Better
      // Auth needs one to keep minting access tokens for FastAPI later
      // (see auth.api.getAccessToken usage, boundary rule 2). Plain login
      // still only requests the default profile/email scope; Gmail +
      // Calendar scopes are requested afterward via a separate "Connect
      // Google Workspace" action (linkSocial) — see auth-client.ts — so a
      // first-time sign-in stays a low-scope, one-click consent screen.
      accessType: "offline",
      prompt: "select_account consent",
    },
  },
});
