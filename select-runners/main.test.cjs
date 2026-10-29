"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const {
  freeOnlyPolicy,
  resolveRunners,
  run,
  validateCatalog,
} = require("./main.cjs");
const catalog = require("./runners.json");

test("selects the first eligible candidate for each role", () => {
  const candidates = {
    linux: [
      { label: "preferred", free: false },
      { label: "fallback", free: true },
      { label: "last", free: true },
    ],
    specialized: [{ label: "specialized", free: false }],
  };
  assert.deepEqual(resolveRunners(candidates, { freeOnly: false }), {
    linux: "preferred",
    specialized: "specialized",
  });
  assert.deepEqual(resolveRunners(candidates, { freeOnly: true }), {
    linux: "fallback",
  });
});

test("uses the workflow repository owner, including Astral forks", () => {
  assert.equal(freeOnlyPolicy("", "astral-sh"), false);
  assert.equal(freeOnlyPolicy("", "Astral-Sh"), false);
  assert.equal(freeOnlyPolicy("", "contributor"), true);
  assert.equal(freeOnlyPolicy("true", "astral-sh"), true);
  assert.equal(freeOnlyPolicy("false", "contributor"), false);
  assert.throws(() => freeOnlyPolicy("", undefined), /REPOSITORY_OWNER/);
  assert.throws(() => freeOnlyPolicy("yes", "astral-sh"), /true or false/);
});

test("rejects unknown and unavailable required roles before emitting outputs", () => {
  assert.throws(
    () => resolveRunners(catalog, { freeOnly: false, required: ["typo"] }),
    /Unknown required runner role: typo/,
  );
  assert.throws(
    () =>
      resolveRunners(catalog, {
        freeOnly: true,
        required: ["ubuntu-aarch64-pgo"],
      }),
    /No eligible runner for required role: ubuntu-aarch64-pgo/,
  );
});

test("the bundled free policy has no paid labels or specialized fallbacks", () => {
  const runners = resolveRunners(catalog, { freeOnly: true });
  assert.equal(Object.hasOwn(runners, "ubuntu-aarch64-pgo"), false);
  assert.equal(Object.hasOwn(runners, "ubuntu-x86_64-codspeed"), false);
  assert.equal(runners["ubuntu-aarch64-4"], "ubuntu-24.04-arm");
  assert.equal(runners["windows-aarch64-8"], "windows-11-arm");
  for (const [role, label] of Object.entries(runners)) {
    assert.ok(
      catalog[role].some(
        (candidate) => candidate.label === label && candidate.free,
      ),
    );
  }
});

test("validates the whole catalog even when selecting only free candidates", () => {
  for (const invalid of [
    null,
    [],
    {},
    { "invalid role": [{ label: "runner", free: true }] },
    { linux: [] },
    { linux: [null] },
    { linux: [{ label: "runner" }] },
    { linux: [{ label: "runner", free: true, priority: 1 }] },
    { linux: [{ label: "", free: true }] },
    { linux: [{ label: "runner\nother=value", free: false }] },
    { linux: [{ label: "runner ", free: false }] },
    { linux: [{ label: "runner", free: "false" }] },
    {
      linux: [
        { label: "runner", free: true },
        { label: "runner", free: false },
      ],
    },
  ]) {
    assert.throws(() => resolveRunners(invalid, { freeOnly: true }));
  }
  assert.equal(validateCatalog(catalog), catalog);
});

test("writes compact action outputs using the bundled catalog without a checkout", (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "select-runners-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const output = path.join(directory, "output");
  run({
    env: {
      GITHUB_REPOSITORY_OWNER: "contributor",
      GITHUB_REPOSITORY: "contributor/uv",
      GITHUB_OUTPUT: output,
      INPUT_REQUIRED: "ubuntu-x86_64-16\nwindows-aarch64-8",
    },
  });
  const [runners, freeOnly, end] = fs.readFileSync(output, "utf8").split("\n");
  assert.equal(freeOnly, "free-only=true");
  assert.equal(end, "");
  assert.deepEqual(
    JSON.parse(runners.slice("runners=".length)),
    resolveRunners(catalog, { freeOnly: true }),
  );
});
