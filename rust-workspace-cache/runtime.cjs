const path = require("node:path");
const { spawnSync } = require("node:child_process");

function profileDirectories(target, value) {
  const profiles = value
    .split(/\r?\n/)
    .map((profile) => profile.trim())
    .filter(Boolean)
    .map((profile) => {
      const directory = path.resolve(target, profile);
      const relative = path.relative(target, directory);
      if (
        !relative ||
        relative === ".." ||
        relative.startsWith(`..${path.sep}`) ||
        path.isAbsolute(relative)
      )
        throw new Error(
          "Cargo profiles must be directories within the target directory",
        );
      return directory;
    });
  if (profiles.length === 0)
    throw new Error("At least one build profile is required");
  return profiles;
}

function runPython(workspace, script, ...scriptArgs) {
  const args = [path.join(__dirname, script), ...scriptArgs];
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
  return result.status ?? 1;
}

module.exports = { profileDirectories, runPython };
