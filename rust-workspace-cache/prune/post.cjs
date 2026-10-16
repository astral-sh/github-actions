const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

if (process.env.STATE_cache) {
  const { workspace, profile, marker } = JSON.parse(process.env.STATE_cache);
  try {
    const result = spawnSync(
      process.platform === "win32" ? "python" : "python3",
      [path.join(__dirname, "prune.py"), profile, marker],
      { cwd: workspace, stdio: "inherit" },
    );
    if (result.error) throw result.error;
    process.exitCode = result.status ?? 1;
  } finally {
    fs.rmSync(path.dirname(marker), { recursive: true, force: true });
  }
}
