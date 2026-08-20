import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone with a self-contained server.js for the Docker image.
  output: "standalone",
  // Pin the workspace root: without it Turbopack walks up to the home directory
  // looking for a lockfile and warns on every build.
  turbopack: { root: path.resolve(__dirname) },
};

export default nextConfig;
