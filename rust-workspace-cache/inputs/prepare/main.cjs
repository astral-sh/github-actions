const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const workspace = fs.realpathSync(process.env.INPUT_WORKSPACE);
const inputRoot =
  process.env["INPUT_CACHE-WORKSPACE-CRATES"] === "false"
    ? null
    : fs.realpathSync(
        execFileSync("git", ["rev-parse", "--show-toplevel"], {
          cwd: workspace,
          encoding: "utf8",
        }).trim(),
      );
const job = [
  process.env.GITHUB_RUN_ID,
  process.env.GITHUB_RUN_ATTEMPT,
  process.env.GITHUB_JOB,
].join("-");
const registry = path.join(
  process.env.RUNNER_TEMP,
  `rust-cache-input-workspaces-${job}.json`,
);
const workspaces = fs.existsSync(registry)
  ? JSON.parse(fs.readFileSync(registry, "utf8"))
  : [];
function contains(parent, child) {
  const relative = path.relative(parent, child);
  return (
    relative === "" ||
    (!relative.startsWith(`..${path.sep}`) &&
      relative !== ".." &&
      !path.isAbsolute(relative))
  );
}
if (
  workspaces.some((entry) => {
    const other = typeof entry === "string" ? { workspace: entry } : entry;
    return (
      contains(other.workspace, workspace) ||
      contains(workspace, other.workspace) ||
      (inputRoot &&
        other.inputRoot &&
        (contains(inputRoot, other.inputRoot) ||
          contains(other.inputRoot, inputRoot)))
    );
  })
) {
  throw new Error(
    "Rust cache workspaces must not overlap, and only one cache may restore input timestamps per Git checkout.",
  );
}
workspaces.push({ workspace, inputRoot });
fs.writeFileSync(registry, JSON.stringify(workspaces));

const id = crypto
  .createHash("sha256")
  .update(workspace)
  .digest("hex")
  .slice(0, 16);
const directory = path.join(process.env.RUNNER_TEMP, `rust-cache-inputs-${id}`);
// A cache miss must not reuse metadata left by an earlier job on the runner.
fs.rmSync(directory, { recursive: true, force: true });
fs.mkdirSync(directory, { recursive: true });
fs.appendFileSync(process.env.GITHUB_OUTPUT, `directory=${directory}\n`);
