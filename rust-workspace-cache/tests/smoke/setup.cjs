const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const workspace = fs.mkdtempSync(
  path.join(process.env.RUNNER_TEMP, "cargo workspace "),
);
fs.mkdirSync(path.join(workspace, "src"));
fs.writeFileSync(
  path.join(workspace, "Cargo.toml"),
  '[package]\nname = "workspace-cache-fixture"\nversion = "0.1.0"\nedition = "2024"\n',
);
fs.writeFileSync(
  path.join(workspace, "src", "lib.rs"),
  "pub fn example() {}\n",
);
// Pruning must skip discovery of the caller's Python project and uv configuration.
fs.writeFileSync(
  path.join(workspace, "pyproject.toml"),
  '[project]\nname = "workspace-cache-fixture"\nversion = "0.0.0"\nrequires-python = "==3.7.*"\ndependencies = []\n\n[tool.uv]\nrequired-version = "==0.0.1"\n',
);
fs.writeFileSync(path.join(workspace, ".python-version"), "3.7\n");
const result = spawnSync("cargo", ["generate-lockfile", "--offline"], {
  cwd: workspace,
  stdio: "inherit",
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

const stale = path.join(
  workspace,
  "target",
  "debug",
  ".fingerprint",
  "workspace-cache-fixture-1111111111111111",
);
fs.mkdirSync(stale, { recursive: true });
fs.writeFileSync(path.join(stale, "lib-workspace_cache_fixture.json"), "{}");
const fingerprint = path.join(stale, "lib-workspace_cache_fixture");
fs.writeFileSync(fingerprint, "stale");
fs.utimesSync(fingerprint, 1, 1);
fs.appendFileSync(process.env.GITHUB_OUTPUT, `workspace=${workspace}\n`);
fs.appendFileSync(process.env.GITHUB_STATE, `workspace=${workspace}\n`);
