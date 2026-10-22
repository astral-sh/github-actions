const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const workspace = fs.realpathSync(process.env.INPUT_WORKSPACE);
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
  workspaces.some(
    (other) => contains(other, workspace) || contains(workspace, other),
  )
) {
  throw new Error(
    "Build input timestamps can only be restored once per workspace in a job",
  );
}
workspaces.push(workspace);
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
