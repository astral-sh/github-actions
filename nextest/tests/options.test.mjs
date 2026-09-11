import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { options, partitionCount } from "../run/options.mjs";

const workspace = path.resolve("checkout");
const input = {
  name: "linux",
  partition: "1",
  partitions: "1",
  arguments: '["--workspace"]',
  directory: ".",
  junit: "target/nextest/**/junit.xml",
  snapshots: "pending-snapshots",
};

test("the planner accepts every supported shard count", () => {
  for (let count = 1; count <= 256; count++)
    assert.equal(partitionCount(String(count)), count);
  for (const value of [
    "",
    "0",
    "-1",
    "1.5",
    "01",
    "1e2",
    "NaN",
    "257",
    "2\n",
  ]) {
    assert.throws(() => partitionCount(value));
  }
});

test("one shard runs the whole suite with unsuffixed artifacts", () => {
  const result = options(input, workspace);
  assert.deepEqual(result.args, ["nextest", "run", "--workspace"]);
  assert.equal(result.outputs["junit-name"], "junit-results-linux");
  assert.equal(result.outputs["snapshots-name"], "pending-snapshots-linux");
});

test("multiple shards use one-based hash partitions and distinct artifacts", () => {
  const result = options(
    { ...input, partition: "2", partitions: "3" },
    workspace,
  );
  assert.deepEqual(result.args, [
    "nextest",
    "run",
    "--partition",
    "hash:2/3",
    "--no-tests=pass",
    "--workspace",
  ]);
  assert.equal(result.outputs["junit-name"], "junit-results-linux-2");
  assert.equal(result.outputs["snapshots-name"], "pending-snapshots-linux-2");
});

test("Cargo and snapshot directories have independent roots", () => {
  const result = options({ ...input, directory: "cargo workspace" }, workspace);
  assert.equal(result.directory, path.join(workspace, "cargo workspace"));
  assert.equal(
    result.outputs["junit-path"],
    path.join(workspace, "cargo workspace", input.junit),
  );
  assert.equal(
    result.outputs["snapshots-path"],
    path.join(workspace, input.snapshots),
  );
});

test("arguments remain individual argv entries", () => {
  const args = ["-E", "test(a b)", "$(touch unexpected)", "a; echo no"];
  assert.deepEqual(
    options(
      { ...input, arguments: JSON.stringify(args) },
      workspace,
    ).args.slice(2),
    args,
  );
});

test("invalid partitions, names, and argument overrides are rejected", () => {
  for (const change of [
    { partition: "2" },
    { name: "../linux" },
    { name: "" },
    { name: "linux\n" },
    { arguments: "{}" },
    { arguments: "[1]" },
    { arguments: '["--partition", "hash:1/2"]' },
    { arguments: '["--partition=hash:1/2"]' },
  ])
    assert.throws(() => options({ ...input, ...change }, workspace));
});

test("empty-shard behavior cannot be overridden in a partitioned run", () => {
  for (const args of [["--no-tests", "fail"], ["--no-tests=fail"]]) {
    assert.throws(() =>
      options(
        { ...input, partitions: "2", arguments: JSON.stringify(args) },
        workspace,
      ),
    );
  }
  assert.deepEqual(
    options({ ...input, arguments: '["--no-tests=warn"]' }, workspace).args,
    ["nextest", "run", "--no-tests=warn"],
  );
});
