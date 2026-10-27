const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

if (["seed", "refresh"].includes(process.env.STATE_phase)) {
  for (const profile of ["debug", "profiling"]) {
    const fingerprints = path.join(
      process.env.STATE_workspace,
      "target",
      profile,
      ".fingerprint",
    );
    const entries = fs.readdirSync(fingerprints);
    assert.ok(
      !entries.includes("workspace-cache-fixture-1111111111111111"),
      "Stale workspace artifacts must be removed",
    );
    assert.equal(
      entries.some((entry) => entry.startsWith("workspace-cache-fixture-")),
      process.env.STATE_mode === "true",
      "Workspace artifacts must match the selected cache mode",
    );
    assert.ok(
      entries.some((entry) => entry.startsWith("cached-dependency-")),
      "Dependency artifacts must remain cached",
    );
  }
  console.log("Local artifacts after cleanup match the requested mode.");
}
