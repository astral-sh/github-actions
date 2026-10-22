const fs = require("node:fs");
const path = require("node:path");
const run = require("./python.cjs");

const workspace = fs.realpathSync(process.env.INPUT_WORKSPACE);
const profiles = process.env.INPUT_PROFILE.split(/\r?\n/)
  .map((profile) => profile.trim())
  .filter(Boolean)
  .map((profile) =>
    path.resolve(workspace, process.env["INPUT_TARGET-DIRECTORY"], profile),
  );
if (profiles.length === 0)
  throw new Error("At least one build profile is required");
const manifest = path.join(process.env.INPUT_DIRECTORY, "manifest.json");
process.exitCode = run(workspace, "restore", manifest, profiles);
if (process.exitCode === 0 && process.env.INPUT_SAVE === "true") {
  fs.appendFileSync(
    process.env.GITHUB_STATE,
    `inputs=${JSON.stringify({ workspace, manifest })}\n`,
  );
}
