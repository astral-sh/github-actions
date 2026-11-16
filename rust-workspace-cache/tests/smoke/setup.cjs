const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const cargoVersion = spawnSync("cargo", ["--version"], { encoding: "utf8" });
if (cargoVersion.error) throw cargoVersion.error;
if (cargoVersion.status !== 0) process.exit(cargoVersion.status ?? 1);
const version = /^cargo (\d+)\.(\d+)\./.exec(cargoVersion.stdout);
if (!version)
  throw new Error(`Unrecognized Cargo version: ${cargoVersion.stdout}`);
const layout =
  Number(version[1]) > 1 || Number(version[2]) >= 100 ? "unit" : "legacy";

const workspace = fs.mkdtempSync(
  path.join(process.env.RUNNER_TEMP, "cargo workspace "),
);
fs.mkdirSync(path.join(workspace, "src"));
fs.writeFileSync(
  path.join(workspace, "Cargo.toml"),
  '[package]\nname = "workspace-cache-fixture"\nversion = "0.1.0"\nedition = "2024"\n\n[dependencies]\ncached-dependency = { path = "dependency" }\n\n[profile.profiling]\ninherits = "dev"\n',
);
fs.writeFileSync(
  path.join(workspace, "src", "lib.rs"),
  "pub fn example() { cached_dependency::example(); }\n",
);
fs.mkdirSync(path.join(workspace, "dependency", "src"), { recursive: true });
fs.writeFileSync(
  path.join(workspace, "dependency", "Cargo.toml"),
  '[package]\nname = "cached-dependency"\nversion = "0.1.0"\nedition = "2024"\n',
);
fs.writeFileSync(
  path.join(workspace, "dependency", "src", "lib.rs"),
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

function createStaleArtifact(target, name, hash) {
  const unit = path.join(target, "build", name, hash);
  const directory =
    layout === "unit"
      ? path.join(unit, "fingerprint")
      : path.join(target, ".fingerprint", `${name}-${hash}`);
  const crate = name.replaceAll("-", "_");
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, `lib-${crate}.json`), "{}");
  const fingerprint = path.join(directory, `lib-${crate}`);
  fs.writeFileSync(fingerprint, "stale");
  fs.utimesSync(fingerprint, 1, 1);
  const artifacts =
    layout === "unit" ? path.join(unit, "out") : path.join(target, "deps");
  fs.mkdirSync(artifacts, { recursive: true });
  fs.writeFileSync(path.join(artifacts, `lib${crate}-${hash}.rlib`), "stale");
}

for (const profile of ["debug", "profiling"]) {
  const target = path.join(workspace, "target", profile);
  createStaleArtifact(target, "workspace-cache-fixture", "1111111111111111");
  createStaleArtifact(target, "cached-dependency", "2222222222222222");
}
fs.appendFileSync(process.env.GITHUB_OUTPUT, `workspace=${workspace}\n`);
fs.appendFileSync(
  process.env.GITHUB_STATE,
  `workspace=${workspace}\nlayout=${layout}\n`,
);
