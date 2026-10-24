const fs = require("node:fs");
const path = require("node:path");
const run = require("../python.cjs");

if (process.env.STATE_cache) {
  const { workspace, profiles, marker, workspaceCrates, target } = JSON.parse(
    process.env.STATE_cache,
  );
  try {
    const args = [path.join(__dirname, "prune.py"), ...profiles, marker];
    if (workspaceCrates === false) {
      args.splice(1, profiles.length, target);
      args.push("--dependencies-only");
    }
    process.exitCode = run(args, { cwd: workspace });
  } finally {
    fs.rmSync(path.dirname(marker), { recursive: true, force: true });
  }
}
