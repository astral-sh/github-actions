const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function setup(context, enabled, profile = "fast-build-nightly") {
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
        INPUT_PROFILE: profile,
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
  assert.deepEqual(state.profiles, [
    path.join(result.workspace, "build-output", "fast-build-nightly"),
  ]);
  assert.ok(fs.statSync(state.marker).isFile());
  const other = JSON.parse(setup(context, true).state.slice("cache=".length));
  assert.notEqual(state.marker, other.marker);
});

test("records each profile independently and accepts Windows line endings", (context) => {
  const result = setup(context, true, "debug\r\n\r\n profiling \r\n");
  const state = JSON.parse(result.state.slice("cache=".length));
  assert.deepEqual(state.profiles, [
    path.join(result.workspace, "build-output", "debug"),
    path.join(result.workspace, "build-output", "profiling"),
  ]);
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

function post(context, results, platform = process.platform) {
  const { state: recorded } = setup(context, true);
  const state = JSON.parse(recorded.slice("cache=".length));
  const calls = [];
  const childProcess = {
    spawnSync(command, args, options) {
      calls.push({ command, args: Array.from(args), options: { ...options } });
      return results.shift();
    },
  };
  const child = { env: { STATE_cache: JSON.stringify(state) }, platform };
  try {
    vm.runInNewContext(
      fs.readFileSync(path.join(__dirname, "post.cjs"), "utf8"),
      {
        __dirname,
        process: child,
        require: (name) => {
          if (name !== "../python.cjs") return require(name);
          const module = { exports: {} };
          vm.runInNewContext(
            fs.readFileSync(path.join(__dirname, "../python.cjs"), "utf8"),
            {
              module,
              process: child,
              require: (name) =>
                name === "node:child_process" ? childProcess : require(name),
            },
          );
          return module.exports;
        },
      },
    );
  } finally {
    assert.ok(!fs.existsSync(path.dirname(state.marker)));
  }
  return { state, calls, exitCode: child.exitCode };
}

test("prefers uv without discovering the caller's Python project or configuration", (context) => {
  const result = post(context, [{ status: 0 }]);
  assert.equal(result.exitCode, 0);
  assert.deepEqual(result.calls, [
    {
      command: "uv",
      args: [
        "run",
        "--no-project",
        "--no-config",
        "--python",
        ">=3.11",
        path.join(__dirname, "prune.py"),
        ...result.state.profiles,
        result.state.marker,
      ],
      options: { cwd: result.state.workspace, stdio: "inherit" },
    },
  ]);
});

for (const [platform, python] of [
  ["linux", "python3"],
  ["darwin", "python3"],
  ["win32", "python"],
]) {
  test(`falls back to ${python} on ${platform} when uv is missing`, (context) => {
    const missing = Object.assign(new Error("uv is missing"), {
      code: "ENOENT",
    });
    const result = post(
      context,
      [{ error: missing }, { status: 0 }, { status: 0 }],
      platform,
    );
    assert.equal(result.exitCode, 0);
    assert.deepEqual(
      result.calls.map((call) => call.command),
      ["uv", python, python],
    );
    assert.deepEqual(result.calls[2].args, [
      path.join(__dirname, "prune.py"),
      ...result.state.profiles,
      result.state.marker,
    ]);
    assert.deepEqual(result.calls[2].options, {
      cwd: result.state.workspace,
      env: undefined,
      stdio: "inherit",
    });
  });
}

test("does not run pruning again when uv reports a failure", (context) => {
  const result = post(context, [{ status: 7 }]);
  assert.equal(result.exitCode, 7);
  assert.deepEqual(
    result.calls.map((call) => call.command),
    ["uv"],
  );
});

test("does not fall back when uv cannot be executed", (context) => {
  const denied = Object.assign(new Error("uv is not executable"), {
    code: "EACCES",
  });
  assert.throws(
    () => post(context, [{ error: denied }]),
    /uv is not executable/,
  );
});
