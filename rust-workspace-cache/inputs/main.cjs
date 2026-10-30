const fs = require("node:fs");
const path = require("node:path");
const run = require("./python.cjs");

const workspace = fs.realpathSync(process.env.INPUT_WORKSPACE);
const target = path.resolve(workspace, process.env["INPUT_TARGET-DIRECTORY"]);
const profiles = process.env.INPUT_PROFILE.split(/\r?\n/)
  .map((profile) => profile.trim())
  .filter(Boolean)
  .map((profile) => path.resolve(target, profile));
if (profiles.length === 0)
  throw new Error("At least one build profile is required");
const name = process.env["INPUT_EXTRA-TARGET-DIRECTORY"];
let extra;
if (name) {
  if (!/^[\w-]+(?:\.[\w-]+)*$/.test(name))
    throw new Error("extra-target-directory must be a single directory name");
  extra = path.join(target, name);
  if (
    profiles.some((profile) => {
      const relative = path.relative(extra.toLowerCase(), profile.toLowerCase());
      return !path.isAbsolute(relative) && relative.split(path.sep)[0] !== "..";
    })
  )
    throw new Error("extra-target-directory must be separate from Cargo profiles");
}
const manifest = path.join(process.env.INPUT_DIRECTORY, "manifest.json");
process.exitCode = run(workspace, "restore", manifest, profiles, extra, target);
if (process.exitCode === 0 && process.env.INPUT_SAVE === "true") {
  fs.appendFileSync(
    process.env.GITHUB_STATE,
    `inputs=${JSON.stringify({ workspace, manifest, extra, target })}\n`,
  );
}
