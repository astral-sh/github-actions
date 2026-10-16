const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

function setup(context, enabled) {
  const directory = fs.mkdtempSync(
    path.join(os.tmpdir(), "workspace-cache-test-"),
  );
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const workspace = path.join(directory, "workspace with spaces");
  fs.mkdirSync(workspace);
  const environment = path.join(directory, "env");
  const state = path.join(directory, "state");
  fs.writeFileSync(environment, "");
  fs.writeFileSync(state, "");
  const result = spawnSync(
    process.execPath,
    [path.join(__dirname, "main.cjs")],
    {
      cwd: workspace,
      env: {
        ...process.env,
        INPUT_ENABLED: String(enabled),
        INPUT_WORKSPACE: workspace,
        "INPUT_TARGET-DIRECTORY": "build-output",
        INPUT_PROFILE: "fast-build-nightly",
        GITHUB_ENV: environment,
        GITHUB_STATE: state,
        RUNNER_TEMP: directory,
      },
      encoding: "utf8",
    },
  );
  assert.equal(result.status, 0, result.stderr);
  return {
    workspace,
    environment: fs.readFileSync(environment, "utf8"),
    state: fs.readFileSync(state, "utf8"),
  };
}

test("records an isolated marker and the external workspace for pruning", (context) => {
  const result = setup(context, true);
  assert.equal(result.environment, "CARGO_UNSTABLE_MTIME_ON_USE=true\n");
  const state = JSON.parse(result.state.slice("cache=".length));
  assert.equal(state.workspace, result.workspace);
  assert.equal(
    state.profile,
    path.join(result.workspace, "build-output", "fast-build-nightly"),
  );
  assert.ok(fs.statSync(state.marker).isFile());
  const other = JSON.parse(setup(context, true).state.slice("cache=".length));
  assert.notEqual(state.marker, other.marker);
});

test("disables usage tracking and pruning when the cache will not be saved", (context) => {
  const result = setup(context, false);
  assert.equal(result.environment, "CARGO_UNSTABLE_MTIME_ON_USE=false\n");
  assert.equal(result.state, "");
});

test("the post step does nothing when no pruning state was recorded", () => {
  const result = spawnSync(
    process.execPath,
    [path.join(__dirname, "post.cjs")],
    {
      env: { ...process.env, STATE_cache: "", PATH: "" },
      encoding: "utf8",
    },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, "");
});
