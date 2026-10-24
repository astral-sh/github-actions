const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

function python() {
  const candidates = [
    { command: process.platform === "win32" ? "python" : "python3" },
  ];
  const toolCache = process.env.RUNNER_TOOL_CACHE;
  if (toolCache) {
    const directory = path.join(toolCache, "Python");
    if (fs.existsSync(directory)) {
      const versions = fs
        .readdirSync(directory)
        .filter(
          (version) =>
            /^3\.(\d+)\.\d+$/.test(version) &&
            Number(version.split(".")[1]) >= 11,
        )
        .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
      for (const version of versions) {
        const root = path.join(
          directory,
          version,
          (process.env.RUNNER_ARCH || process.arch).toLowerCase(),
        );
        const command = path.join(
          root,
          process.platform === "win32" ? "python.exe" : "bin/python3",
        );
        const env = { ...process.env };
        if (process.platform === "linux") {
          env.LD_LIBRARY_PATH = [path.join(root, "lib"), env.LD_LIBRARY_PATH]
            .filter(Boolean)
            .join(path.delimiter);
        }
        candidates.push({ command, env });
      }
    }
  }
  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, ["-c", "import tomllib"], {
      env: candidate.env,
      stdio: "ignore",
    });
    if (result.status === 0) return candidate;
    if (result.error && result.error.code !== "ENOENT") throw result.error;
  }
  throw new Error(
    "Python 3.11 or newer is required; install uv or configure Python before this action.",
  );
}

module.exports = function run(args, options = {}) {
  let result = spawnSync(
    "uv",
    ["run", "--no-project", "--no-config", "--python", ">=3.11", ...args],
    { ...options, stdio: "inherit" },
  );
  if (result.error?.code === "ENOENT") {
    const selected = python();
    result = spawnSync(selected.command, args, {
      ...options,
      env: selected.env,
      stdio: "inherit",
    });
  }
  if (result.error) throw result.error;
  return result.status ?? 1;
};
