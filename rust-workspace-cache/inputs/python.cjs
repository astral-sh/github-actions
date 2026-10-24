const path = require("node:path");
const run = require("../python.cjs");

module.exports = function (workspace, operation, manifest, profiles = []) {
  return run(
    [path.join(__dirname, "inputs.py"), operation, manifest, ...profiles],
    { cwd: workspace },
  );
};
