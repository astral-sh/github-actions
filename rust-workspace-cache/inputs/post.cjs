const run = require("./python.cjs");

if (process.env.STATE_inputs) {
  const { workspace, manifest, extra, target } = JSON.parse(process.env.STATE_inputs);
  process.exitCode = run(workspace, "save", manifest, [], extra, target);
}
