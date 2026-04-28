// Drift check: regenerate `shared-types/src/index.ts` from
// `docs/api-contract.yaml` into a temp file and compare with the
// committed file. Exits non-zero if they diverge.
//
// CI runs this in stage 1 alongside the OpenAPI drift check.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..");
const sharedTypes = join(repo, "shared-types");
const contract = join(repo, "docs", "api-contract.yaml");
const committed = join(sharedTypes, "src", "index.ts");

const tmpDir = mkdtempSync(join(tmpdir(), "vc-shared-types-"));
const tmpOut = join(tmpDir, "fresh.ts");

try {
  execFileSync(
    "pnpm",
    ["exec", "openapi-typescript", contract, "-o", tmpOut],
    { cwd: sharedTypes, stdio: ["ignore", "ignore", "inherit"] },
  );
  const fresh = readFileSync(tmpOut, "utf-8");
  const onDisk = readFileSync(committed, "utf-8");
  if (fresh !== onDisk) {
    process.stderr.write(
      `shared-types drift: ${committed} is out of sync with ${contract}.\n` +
        "Run `pnpm --filter @vaultchain/shared-types build` and commit.\n",
    );
    process.exit(1);
  }
  process.stdout.write("shared-types in sync.\n");
} finally {
  rmSync(tmpDir, { recursive: true, force: true });
}
