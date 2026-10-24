const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

function helper(results, environment = {}, platform = "linux", versions = []) {
  const calls = [];
  const module = { exports: {} };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, "python.cjs"), "utf8"),
    {
      __dirname,
      module,
      process: { env: environment, platform, arch: "x64" },
      require(name) {
        if (name === "node:fs")
          return { existsSync: () => true, readdirSync: () => versions };
        if (name === "node:child_process")
          return {
            spawnSync(command, args, options) {
              calls.push({ command, args: Array.from(args), options });
              assert.ok(results.length, "unexpected subprocess");
              return results.shift();
            },
          };
        return require(name);
      },
    },
  );
  return { run: module.exports, calls };
}

const absent = { error: { code: "ENOENT" } };

test("uv failures do not retry the operation", () => {
  const { run, calls } = helper([{ status: 7 }]);
  assert.equal(run(["cache.py", "prepare", "configuration"]), 7);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "uv");
  assert.deepEqual(calls[0].args.slice(0, 5), [
    "run",
    "--no-project",
    "--no-config",
    "--python",
    ">=3.11",
  ]);
});

for (const [platform, command] of [
  ["linux", "python3"],
  ["darwin", "python3"],
  ["win32", "python"],
]) {
  test(`uses the default Python on ${platform} when it supports TOML`, () => {
    const { run, calls } = helper(
      [absent, { status: 0 }, { status: 0 }],
      {},
      platform,
    );
    assert.equal(run(["cache.py", "prepare", "configuration"]), 0);
    assert.deepEqual(
      calls.map((c) => c.command),
      ["uv", command, command],
    );
    assert.deepEqual(calls[2].args, ["cache.py", "prepare", "configuration"]);
  });
}

test("an older default Python falls back to the runner tool cache", () => {
  const { run, calls } = helper(
    [absent, { status: 1 }, { status: 0 }, { status: 0 }],
    {
      RUNNER_TOOL_CACHE: "/tools",
      RUNNER_ARCH: "ARM64",
      LD_LIBRARY_PATH: "/existing",
    },
    "linux",
    ["3.10.12", "3.11.14", "3.13.1", "invalid"],
  );
  assert.equal(run(["cache.py", "prepare", "configuration"]), 0);
  assert.equal(calls[2].command, "/tools/Python/3.13.1/arm64/bin/python3");
  assert.equal(calls[3].command, calls[2].command);
  assert.equal(
    calls[3].options.env.LD_LIBRARY_PATH,
    "/tools/Python/3.13.1/arm64/lib:/existing",
  );
});

test("an operation failure is not retried with another interpreter", () => {
  const { run, calls } = helper([absent, { status: 0 }, { status: 9 }]);
  assert.equal(run(["cache.py", "cleanup", "configuration"]), 9);
  assert.equal(calls.length, 3);
});

test("reports a missing supported interpreter before running the operation", () => {
  const { run } = helper([absent, { status: 1 }]);
  assert.throws(
    () => run(["cache.py", "prepare", "configuration"]),
    /Python 3.11 or newer is required/,
  );
});
