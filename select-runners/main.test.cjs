"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { freeOnlyPolicy, resolveRunners, run } = require("./main.cjs");
const inventory = require("./runners.json");

test("each inventory label belongs to exactly one group", () => {
  const seen = new Set();
  for (const [group, labels] of Object.entries(inventory)) {
    assert.ok(Array.isArray(labels) && labels.length > 0, group);
    for (const label of labels) {
      assert.match(label, /^[a-z0-9][a-z0-9._-]*$/);
      assert.ok(!seen.has(label), `Duplicate runner label: ${label}`);
      seen.add(label);
    }
  }
});

test("selects additional provider labels and their explicit free fallbacks", () => {
  const roles = {
    "ubuntu-x86_64-4": ["namespace-profile-ubuntu-24-04-4", "ubuntu-24.04"],
    "windows-build": ["depot-windows-2025-32", "windows-2025"],
    "windows-large": ["namespace-profile-windows-2022-x86-64-32x64"],
    "windows-preview": ["github-windows-11-preview-aarch64-8"],
  };
  const preferred = resolveRunners({ freeOnly: false, roles });
  assert.equal(
    preferred["ubuntu-x86_64-4"],
    "namespace-profile-ubuntu-24-04-4",
  );
  assert.equal(preferred["windows-build"], "depot-windows-2025-32");
  assert.equal(
    preferred["windows-large"],
    "namespace-profile-windows-2022-x86-64-32x64",
  );
  assert.equal(
    preferred["windows-preview"],
    "github-windows-11-preview-aarch64-8",
  );
  assert.equal(preferred["ubuntu-x86_64-16"], "depot-ubuntu-24.04-16");

  const free = resolveRunners({ freeOnly: true, roles });
  assert.equal(free["ubuntu-x86_64-4"], "ubuntu-24.04");
  assert.equal(free["windows-build"], "windows-2025");
  assert.ok(!Object.hasOwn(free, "windows-large"));
  assert.ok(!Object.hasOwn(free, "windows-preview"));
  assert.ok(
    Object.values(free).every((label) =>
      inventory["github-standard"].includes(label),
    ),
  );
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

test("rejects unknown and unavailable required roles", () => {
  assert.throws(
    () => resolveRunners({ freeOnly: false, required: ["typo"] }),
    /Unknown required runner role: typo/,
  );
  assert.throws(
    () => resolveRunners({ freeOnly: true, required: ["ubuntu-aarch64-pgo"] }),
    /No eligible runner for required role: ubuntu-aarch64-pgo/,
  );
  const free = resolveRunners({ freeOnly: true });
  assert.ok(!Object.hasOwn(free, "ubuntu-x86_64-codspeed"));
  assert.ok(!Object.hasOwn(free, "ubuntu-aarch64-pgo"));
  assert.equal(free["ubuntu-aarch64-4"], "ubuntu-24.04-arm");
  assert.equal(free["windows-aarch64-8"], "windows-11-arm");
});

test("validates every candidate even when an earlier label is eligible", () => {
  for (const roles of [
    null,
    [],
    { "invalid role": ["ubuntu-24.04"] },
    { linux: [] },
    { linux: "ubuntu-24.04" },
    { linux: ["ubuntu-24.04", "depot-ubuntu-24.04-96"] },
    { linux: ["ubuntu-24.04", "ubuntu-24.04"] },
    { linux: [{ label: "depot-ubuntu-24.04-16", free: true }] },
  ]) {
    assert.throws(() => resolveRunners({ freeOnly: true, roles }));
  }
});

test("writes the resolved custom and default roles to the action outputs", (context) => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "select-runners-"));
  context.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const output = path.join(directory, "output");
  const roles = { "macos-build": ["depot-macos-26", "macos-15"] };
  run({
    env: {
      GITHUB_REPOSITORY_OWNER: "contributor",
      GITHUB_OUTPUT: output,
      INPUT_ROLES: JSON.stringify(roles),
      INPUT_REQUIRED: "ubuntu-x86_64-16\nmacos-build",
    },
  });
  const [runners, freeOnly, end] = fs.readFileSync(output, "utf8").split("\n");
  assert.equal(freeOnly, "free-only=true");
  assert.equal(end, "");
  assert.deepEqual(JSON.parse(runners.slice("runners=".length)), {
    ...resolveRunners({ freeOnly: true }),
    "macos-build": "macos-15",
  });
});
