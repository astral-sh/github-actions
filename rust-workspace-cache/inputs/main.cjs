const fs = require("node:fs");
const path = require("node:path");
const { profileDirectories, runPython } = require("../runtime.cjs");

const workspace = fs.realpathSync(process.env.INPUT_WORKSPACE);
const target = path.resolve(workspace, process.env["INPUT_TARGET-DIRECTORY"]);
const profiles = profileDirectories(target, process.env.INPUT_PROFILE);
const manifest = path.join(process.env.INPUT_DIRECTORY, "manifest.json");
const options = ["--target-directory", target];
const name = process.env["INPUT_EXTRA-TARGET-DIRECTORY"];
if (name) {
  if (!/^[\w-]+(?:\.[\w-]+)*$/.test(name))
    throw new Error("extra-target-directory must be a single directory name");
  const overlapsProfile = profiles.some((profile) => {
    const relative = path.relative(target.toLowerCase(), profile.toLowerCase());
    return relative.split(path.sep)[0] === name.toLowerCase();
  });
  if (overlapsProfile)
    throw new Error(
      "extra-target-directory must be separate from Cargo profiles",
    );
  options.push("--extra-target-directory", path.join(target, name));
}
process.exitCode = runPython(
  workspace,
  "inputs/inputs.py",
  "restore",
  manifest,
  ...profiles,
  ...options,
);
if (process.exitCode === 0 && process.env.INPUT_SAVE === "true") {
  fs.appendFileSync(
    process.env.GITHUB_STATE,
    `inputs=${JSON.stringify({ workspace, manifest, options })}\n`,
  );
}
