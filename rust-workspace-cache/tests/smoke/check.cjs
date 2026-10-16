const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const fingerprints = path.join(
  process.env.STATE_workspace,
  "target",
  "debug",
  ".fingerprint",
);
assert.ok(
  !fs.existsSync(
    path.join(fingerprints, "workspace-cache-fixture-1111111111111111"),
  ),
  "The stale workspace fingerprint must be pruned",
);
assert.ok(
  fs
    .readdirSync(fingerprints)
    .some((entry) => entry.startsWith("workspace-cache-fixture-")),
  "The active workspace fingerprint must remain cached",
);
console.log("Superseded workspace artifacts were pruned.");
