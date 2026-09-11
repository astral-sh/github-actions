import { appendFileSync } from "node:fs";
import { partitionCount } from "../run/options.mjs";

try {
  const count = partitionCount(process.env.INPUT_SHARDS);
  const partitions = Array.from({ length: count }, (_, index) => index + 1);
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    `partitions=${JSON.stringify(partitions)}\n`,
  );
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
