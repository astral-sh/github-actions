const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

for (const profile of ["dev", "profiling"]) {
  const result = spawnSync(
    "cargo",
    [
      "build",
      "--verbose",
      "--verbose",
      "--locked",
      "--offline",
      "-Zchecksum-freshness",
      "--profile",
      profile,
      "--message-format=json",
    ],
    { cwd: process.env.FIXTURE_WORKSPACE, encoding: "utf8" },
  );
  process.stderr.write(result.stderr);
  if (result.error) throw result.error;
  assert.equal(result.status, 0);
  const artifacts = result.stdout
    .split(/\r?\n/)
    .filter((line) => line.startsWith("{"))
    .map((line) => JSON.parse(line))
    .filter(
      (message) =>
        message.reason === "compiler-artifact" &&
        message.target.kind.includes("lib"),
    );
  if (process.env.FIXTURE_PHASE === "restore") {
    const dependency = artifacts.find(
      (artifact) => artifact.target.name === "cached_dependency",
    );
    const workspace = artifacts.find(
      (artifact) => artifact.target.name === "workspace_cache_fixture",
    );
    assert.equal(
      dependency.fresh,
      true,
      "Dependency compilation must be reused",
    );
    assert.equal(
      workspace.fresh,
      process.env.FIXTURE_MODE === "true",
      "Workspace reuse must match the cache mode",
    );
  }
}
if (process.env.FIXTURE_PHASE === "seed") {
  const result = spawnSync(
    "cargo",
    [
      "install",
      "--locked",
      "--offline",
      "--path",
      path.join(process.env.FIXTURE_WORKSPACE, "..", "tool"),
    ],
    { stdio: "inherit" },
  );
  if (result.error) throw result.error;
  assert.equal(result.status, 0);
} else {
  const result = spawnSync("cache-fixture-tool", [], { encoding: "utf8" });
  if (result.error) throw result.error;
  assert.equal(result.status, 0);
  assert.equal(result.stdout.trim(), "cached tool");
}
