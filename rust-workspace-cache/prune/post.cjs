const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

if (process.env.STATE_cache) {
  const { workspace, profiles, marker } = JSON.parse(process.env.STATE_cache);
  try {
    const args = [path.join(__dirname, "prune.py"), ...profiles, marker];
    const options = { cwd: workspace, stdio: "inherit" };
    let result = spawnSync(
      "uv",
      ["run", "--no-project", "--no-config", "--python", ">=3.11", ...args],
      options,
    );
    if (result.error?.code === "ENOENT") {
      result = spawnSync(
        process.platform === "win32" ? "python" : "python3",
        args,
        options,
      );
    }
    if (result.error) throw result.error;
    process.exitCode = result.status ?? 1;
  } finally {
    fs.rmSync(path.dirname(marker), { recursive: true, force: true });
  }
}
