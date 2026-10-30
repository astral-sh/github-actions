const { runPython } = require("../runtime.cjs");

if (process.env.STATE_inputs) {
  const { workspace, manifest, options } = JSON.parse(process.env.STATE_inputs);
  process.exitCode = runPython(
    workspace,
    "inputs/inputs.py",
    "save",
    manifest,
    ...options,
  );
}
