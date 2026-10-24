const fs = require("node:fs");
const path = require("node:path");
const run = require("../python.cjs");

const directory = fs.mkdtempSync(
  path.join(process.env.RUNNER_TEMP, "rust-cache-config-"),
);
const configuration = path.join(directory, "config.json");
process.exitCode = run("prepare", configuration);
if (process.exitCode === 0) {
  fs.appendFileSync(
    process.env.GITHUB_OUTPUT,
    `configuration=${configuration}\n`,
  );
  if (process.env.CARGO_INCREMENTAL === undefined) {
    fs.appendFileSync(process.env.GITHUB_ENV, "CARGO_INCREMENTAL=0\n");
  }
}
