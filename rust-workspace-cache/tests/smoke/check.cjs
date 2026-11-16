const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

for (const profile of ["debug", "profiling"]) {
  const target = path.join(process.env.STATE_workspace, "target", profile);
  if (process.env.STATE_layout === "unit") {
    const units = path.join(target, "build", "workspace-cache-fixture");
    assert.ok(
      !fs.existsSync(path.join(units, "1111111111111111")),
      "The stale workspace unit must be pruned",
    );
    assert.ok(
      fs.readdirSync(units).some((entry) =>
        fs.existsSync(
          path.join(units, entry, "fingerprint", "lib-workspace_cache_fixture"),
        ),
      ),
      "The active workspace unit must remain cached",
    );
    const dependency = path.join(target, "build", "cached-dependency");
    assert.ok(
      fs.readdirSync(dependency).some((entry) =>
        fs.existsSync(
          path.join(
            dependency,
            entry,
            "out",
            `libcached_dependency-${entry}.rlib`,
          ),
        ),
      ),
      "Cached dependency artifacts must remain",
    );
  } else {
    const fingerprints = path.join(target, ".fingerprint");
    assert.ok(
      !fs.existsSync(
        path.join(fingerprints, "workspace-cache-fixture-1111111111111111"),
      ),
      "The stale workspace fingerprint must be pruned",
    );
    assert.ok(
      !fs.existsSync(
        path.join(
          target,
          "deps",
          "libworkspace_cache_fixture-1111111111111111.rlib",
        ),
      ),
      "The stale workspace artifact must be pruned",
    );
    assert.ok(
      fs
        .readdirSync(fingerprints)
        .some((entry) => entry.startsWith("workspace-cache-fixture-")),
      "The active workspace fingerprint must remain cached",
    );
    assert.ok(
      fs.readdirSync(path.join(target, "deps")).some((entry) =>
        /^libcached_dependency-[0-9a-f]{16}\.rlib$/.test(entry),
      ),
      "Cached dependency artifacts must remain",
    );
  }
}
console.log("Superseded workspace artifacts were pruned.");
