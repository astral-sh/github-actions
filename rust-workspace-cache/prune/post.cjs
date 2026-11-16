const fs = require("node:fs");
const path = require("node:path");
const { runPython } = require("../runtime.cjs");

if (process.env.STATE_cache) {
  const { workspace, target, profiles, marker } = JSON.parse(
    process.env.STATE_cache,
  );
  try {
    process.exitCode = runPython(
      workspace,
      "prune/prune.py",
      ...profiles,
      marker,
      "--target-directory",
      target,
    );
  } finally {
    fs.rmSync(path.dirname(marker), { recursive: true, force: true });
  }
}
