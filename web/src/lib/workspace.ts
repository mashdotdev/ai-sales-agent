import { prisma } from "@/lib/prisma";

/**
 * Single-workspace-for-v1 (see documents/plan.md) — nothing creates a
 * Workspace row anywhere else, and KnowledgeDoc.workspaceId is a required
 * FK. Called on dashboard load and again from the knowledge API routes;
 * idempotent after the first call ever creates the row, so it's cheap and
 * safe to call repeatedly rather than threading a workspaceId through props.
 */
export async function getOrCreateWorkspace() {
  const existing = await prisma.workspace.findFirst();
  if (existing) return existing;

  return prisma.workspace.create({
    data: { name: "My Workspace" },
  });
}
