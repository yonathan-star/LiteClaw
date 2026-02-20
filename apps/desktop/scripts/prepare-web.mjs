import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(process.cwd());
const dist = resolve(root, "dist");
const srcDir = resolve(root, "src");
const indexFile = resolve(root, "index.html");

if (existsSync(dist)) {
  rmSync(dist, { recursive: true, force: true });
}
mkdirSync(dist, { recursive: true });
cpSync(indexFile, resolve(dist, "index.html"));
cpSync(srcDir, resolve(dist, "src"), { recursive: true });
