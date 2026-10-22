const fs = require("node:fs");
const path = require("node:path");

const enabled = process.env.INPUT_ENABLED === "true";
fs.appendFileSync(
  process.env.GITHUB_ENV,
  `CARGO_UNSTABLE_MTIME_ON_USE=${enabled}\n`,
);

if (enabled) {
  const workspace = path.resolve(process.env.INPUT_WORKSPACE);
  const profiles = process.env.INPUT_PROFILE.split(/\r?\n/)
    .map((profile) => profile.trim())
    .filter(Boolean)
    .map((profile) =>
      path.resolve(workspace, process.env["INPUT_TARGET-DIRECTORY"], profile),
    );
  if (profiles.length === 0)
    throw new Error("At least one build profile is required");
  const directory = fs.mkdtempSync(
    path.join(process.env.RUNNER_TEMP, "rust-workspace-cache-"),
  );
  const marker = path.join(directory, "marker");
  fs.writeFileSync(marker, "");
  fs.appendFileSync(
    process.env.GITHUB_STATE,
    `cache=${JSON.stringify({ workspace, profiles, marker })}\n`,
  );
}
