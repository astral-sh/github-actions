const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const directory = path.join(process.env.RUNNER_TEMP, "cargo cache fixture");
fs.rmSync(directory, { recursive: true, force: true });
const workspace = path.join(directory, "workspace");
for (const [name, manifest, source] of [
  [
    "workspace",
    '[package]\nname="workspace-cache-fixture"\nversion="0.1.0"\nedition="2024"\n[dependencies]\ncached-dependency={path="../../cargo-cache-dependency"}\n[profile.profiling]\ninherits="dev"\n',
    "pub fn example() { cached_dependency::example(); }\n",
  ],
  [
    "dependency",
    '[package]\nname="cached-dependency"\nversion="0.1.0"\nedition="2024"\n',
    "pub fn example() {}\n",
  ],
  [
    "tool",
    '[package]\nname="cache-fixture-tool"\nversion="0.1.0"\nedition="2024"\n',
    'fn main() { println!("cached tool"); }\n',
  ],
]) {
  const root =
    name === "dependency"
      ? path.join(process.env.RUNNER_TEMP, "cargo-cache-dependency")
      : path.join(directory, name);
  fs.rmSync(root, { recursive: true, force: true });
  fs.mkdirSync(path.join(root, "src"), { recursive: true });
  fs.writeFileSync(path.join(root, "Cargo.toml"), manifest);
  fs.writeFileSync(
    path.join(root, "src", name === "tool" ? "main.rs" : "lib.rs"),
    source,
  );
}
fs.writeFileSync(
  path.join(workspace, "build.rs"),
  'fn main() { println!("cargo:rerun-if-changed=input.txt"); }\n',
);
fs.writeFileSync(path.join(workspace, "input.txt"), "build input\n");
// Helpers must not discover the caller's Python project or uv configuration.
fs.writeFileSync(
  path.join(workspace, "pyproject.toml"),
  '[project]\nname="workspace-cache-fixture"\nversion="0.0.0"\nrequires-python="==3.7.*"\ndependencies=[]\n[tool.uv]\nrequired-version="==0.0.1"\n',
);
fs.writeFileSync(path.join(workspace, ".python-version"), "3.7\n");
if (["refresh", "refreshed"].includes(process.env.INPUT_PHASE)) {
  fs.appendFileSync(
    path.join(workspace, "src", "lib.rs"),
    "// Changed source.\n",
  );
}
for (const [command, args, cwd] of [
  ["cargo", ["generate-lockfile", "--offline"], workspace],
  ["cargo", ["generate-lockfile", "--offline"], path.join(directory, "tool")],
  ["git", ["init", "--quiet"], workspace],
  ["git", ["add", "."], workspace],
]) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
if (process.env.INPUT_PHASE === "seed") {
  for (const profile of ["debug", "profiling"]) {
    const stale = path.join(
      workspace,
      "target",
      profile,
      ".fingerprint",
      "workspace-cache-fixture-1111111111111111",
    );
    fs.mkdirSync(stale, { recursive: true });
    fs.writeFileSync(
      path.join(stale, "lib-workspace_cache_fixture.json"),
      "{}",
    );
    const fingerprint = path.join(stale, "lib-workspace_cache_fixture");
    fs.writeFileSync(fingerprint, "stale");
    fs.utimesSync(fingerprint, 1, 1);
  }
}
fs.appendFileSync(process.env.GITHUB_OUTPUT, `workspace=${workspace}\n`);
fs.appendFileSync(
  process.env.GITHUB_STATE,
  `workspace=${workspace}\nmode=${process.env["INPUT_CACHE-WORKSPACE-CRATES"]}\nphase=${process.env.INPUT_PHASE}\n`,
);
