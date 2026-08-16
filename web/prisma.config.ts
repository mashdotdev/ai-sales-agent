import { defineConfig } from "prisma/config";
import { config } from "dotenv";
import { resolve } from "path";

// Prisma CLI commands (migrate, studio, ...) run outside Next.js, so they
// don't get .env.local for free the way `next dev` does — load it explicitly.
config({ path: resolve(__dirname, ".env.local") });

export default defineConfig({
  datasource: {
    url: process.env.DATABASE_URL ?? "",
  },
});
