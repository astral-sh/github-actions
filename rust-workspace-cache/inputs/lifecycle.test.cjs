const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function fixture(context) {
  const directory = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "cache-input-lifecycle-")),
  );
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const workspace = path.join(directory, "workspace with spaces");
  fs.mkdirSync(workspace);
  return { directory, workspace };
}

function prepare(directory, workspace, job = "1", extra = "") {
  const output = path.join(directory, "output");
  fs.writeFileSync(output, "");
  const result = spawnSync(
    process.execPath,
    [path.join(__dirname, "prepare/main.cjs")],
    {
      env: {
        ...process.env,
        INPUT_WORKSPACE: workspace,
        "INPUT_EXTRA-TARGET-DIRECTORY": extra,
        RUNNER_TEMP: directory,
        GITHUB_OUTPUT: output,
        GITHUB_RUN_ID: job,
        GITHUB_RUN_ATTEMPT: "1",
        GITHUB_JOB: "test",
      },
      encoding: "utf8",
    },
  );
  return {
    ...result,
    directory: fs
      .readFileSync(output, "utf8")
      .trim()
      .slice("directory=".length),
  };
}

test("isolates metadata from source inputs and clears leftovers between jobs", (context) => {
  const { directory, workspace } = fixture(context);
  const first = prepare(directory, workspace);
  assert.equal(first.status, 0, first.stderr);
  assert.equal(path.dirname(first.directory), directory);
  assert.notEqual(first.directory, workspace);
  fs.writeFileSync(path.join(first.directory, "manifest.json"), "stale");
  const next = prepare(directory, workspace, "2");
  assert.equal(next.status, 0, next.stderr);
  assert.equal(next.directory, first.directory);
  assert.deepEqual(fs.readdirSync(next.directory), []);
  const withExtra = prepare(directory, workspace, "3", "hawk-fragments");
  assert.equal(withExtra.status, 0, withExtra.stderr);
  assert.notEqual(withExtra.directory, first.directory);
});

test("rejects overlapping snapshots but permits independent workspaces", (context) => {
  const { directory, workspace } = fixture(context);
  assert.equal(prepare(directory, workspace).status, 0);
  const nested = path.join(workspace, "nested");
  fs.mkdirSync(nested);
  assert.notEqual(prepare(directory, nested).status, 0);
  assert.notEqual(prepare(directory, workspace).status, 0);
  const adjacent = `${workspace}-other`;
  fs.mkdirSync(adjacent);
  assert.equal(prepare(directory, adjacent).status, 0);
});

function lifecycle(context, save, status = 0, extra = "") {
  const { directory, workspace } = fixture(context);
  const state = path.join(directory, "state");
  fs.writeFileSync(state, "");
  const calls = [];
  const child = {
    env: {
      INPUT_WORKSPACE: workspace,
      INPUT_PROFILE: "debug\r\n profiling\r\n",
      "INPUT_TARGET-DIRECTORY": "build output",
      "INPUT_EXTRA-TARGET-DIRECTORY": extra,
      INPUT_DIRECTORY: directory,
      INPUT_SAVE: String(save),
      GITHUB_STATE: state,
    },
  };
  const execute = (file) =>
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, file), "utf8"), {
      process: child,
      require: (name) =>
        name === "./python.cjs"
          ? (...args) => {
              calls.push(JSON.parse(JSON.stringify(args)));
              return status;
            }
          : require(name),
    });
  execute("main.cjs");
  const recorded = fs.readFileSync(state, "utf8");
  child.env = {
    STATE_inputs: recorded ? recorded.slice("inputs=".length).trim() : "",
  };
  execute("post.cjs");
  return { directory, workspace, recorded, calls, status: child.exitCode };
}

test("restores read-only hits without recording replacement metadata", (context) => {
  const result = lifecycle(context, false);
  assert.equal(result.status, 0);
  assert.equal(result.recorded, "");
  assert.deepEqual(result.calls, [
    [
      result.workspace,
      "restore",
      path.join(result.directory, "manifest.json"),
      [
        path.join(result.workspace, "build output/debug"),
        path.join(result.workspace, "build output/profiling"),
      ],
      null,
    ],
  ]);
});

test("captures successful builds before the artifact cache is saved", (context) => {
  const result = lifecycle(context, true, 0, "hawk-fragments");
  assert.deepEqual(
    result.calls.map((call) => call[1]),
    ["restore", "save"],
  );
  const directory = path.join(result.workspace, "build output", "hawk-fragments");
  assert.deepEqual(result.calls.map((call) => call[4]), [directory, directory]);
});

test("rejects extra directories outside the target or used by Cargo", (context) => {
  assert.throws(() => lifecycle(context, true, 0, "../outside"), /single directory name/);
  assert.throws(() => lifecycle(context, true, 0, "debug"), /separate from Cargo profiles/);
});

test("does not save metadata when restoration fails", (context) => {
  const result = lifecycle(context, true, 7);
  assert.equal(result.status, 7);
  assert.equal(result.recorded, "");
  assert.equal(result.calls.length, 1);
});

test("Python invocation prefers uv and only falls back when it is absent", () => {
  for (const [platform, fallback] of [
    ["linux", "python3"],
    ["win32", "python"],
  ]) {
    const calls = [];
    const module = { exports: {} };
    vm.runInNewContext(
      fs.readFileSync(path.join(__dirname, "python.cjs"), "utf8"),
      {
        __dirname,
        module,
        process: { platform },
        require: (name) =>
          name === "node:child_process"
            ? {
                spawnSync(command, args, options) {
                  calls.push({
                    command,
                    args: Array.from(args),
                    options: { ...options },
                  });
                  return calls.length === 1
                    ? { error: { code: "ENOENT" } }
                    : { status: 0 };
                },
              }
            : require(name),
      },
    );
    assert.equal(
      module.exports("workspace", "restore", "manifest", ["profile"]),
      0,
    );
    assert.deepEqual(
      calls.map((call) => call.command),
      ["uv", fallback],
    );
    assert.deepEqual(calls[0].args.slice(0, 5), [
      "run",
      "--no-project",
      "--no-config",
      "--python",
      ">=3.11",
    ]);
    assert.deepEqual(calls[1].args, [
      path.join(__dirname, "inputs.py"),
      "restore",
      "manifest",
      "profile",
    ]);
  }
});
