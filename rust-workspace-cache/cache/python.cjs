const path = require("node:path");
const { spawnSync } = require("node:child_process");

module.exports = function run(operation, configuration) {
  const args = [path.join(__dirname, "cache.py"), operation, configuration];
  const options = { stdio: "inherit" };
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
  return result.status ?? 1;
};
