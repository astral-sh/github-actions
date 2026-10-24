const fs = require("node:fs");
const run = require("./python.cjs");

const configuration = process.env.INPUT_CONFIGURATION;
process.exitCode = run("restore", configuration);
if (process.exitCode === 0 && process.env.INPUT_SAVE === "true") {
  fs.appendFileSync(
    process.env.GITHUB_STATE,
    `configuration=${configuration}\n`,
  );
}
