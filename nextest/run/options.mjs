import path from "node:path";

export function partitionCount(value) {
  const count = Number(value);
  if (
    !Number.isSafeInteger(count) ||
    count < 1 ||
    count > 256 ||
    String(count) !== String(value)
  ) {
    throw new Error("The shard count must be an integer from 1 through 256");
  }
  return count;
}

export function options(input, workspace) {
  const partitions = partitionCount(input.partitions);
  const partition = partitionCount(input.partition);
  if (partition > partitions) {
    throw new Error("The partition number exceeds the shard count");
  }
  if (
    typeof input.name !== "string" ||
    !/^[a-zA-Z0-9]/.test(input.name) ||
    /[^a-zA-Z0-9_.-]/.test(input.name)
  ) {
    throw new Error(
      "The artifact name must contain only letters, numbers, _, ., or -",
    );
  }
  const args = JSON.parse(input.arguments);
  if (!Array.isArray(args) || args.some((arg) => typeof arg !== "string")) {
    throw new Error("The nextest arguments must be a JSON array of strings");
  }
  if (
    args.some((arg) => arg === "--partition" || arg.startsWith("--partition="))
  ) {
    throw new Error("Use the partition inputs instead of passing --partition");
  }
  const directory = path.resolve(workspace, input.directory);
  const suffix = partitions === 1 ? "" : `-${partition}`;
  return {
    directory,
    args: [
      "nextest",
      "run",
      ...(partitions === 1
        ? []
        : ["--partition", `hash:${partition}/${partitions}`]),
      ...args,
    ],
    outputs: {
      "junit-name": `junit-results-${input.name}${suffix}`,
      "junit-path": path.resolve(directory, input.junit),
      "snapshots-name": `pending-snapshots-${input.name}${suffix}`,
      "snapshots-path": path.resolve(workspace, input.snapshots),
    },
  };
}
