import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { auth } from "@/server/auth";
import { prisma } from "@/lib/prisma";
import { DashboardShell } from "@/components/dashboard-shell";

export default async function DashboardPage() {
  const session = await auth.api.getSession({ headers: await headers() });

  if (!session) {
    redirect("/sign-in");
  }

  const googleAccount = await prisma.account.findFirst({
    where: { userId: session.user.id, providerId: "google" },
    select: { refreshToken: true },
  });

  return (
    <DashboardShell
      userName={session.user.name}
      hasGoogleWorkspace={Boolean(googleAccount?.refreshToken)}
    />
  );
}
