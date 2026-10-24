const run = require("./python.cjs");

if (process.env.STATE_configuration) {
  process.exitCode = run("save", process.env.STATE_configuration);
}
