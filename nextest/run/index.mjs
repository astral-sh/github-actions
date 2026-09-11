import { spawnSync } from "node:child_process";
import { appendFileSync } from "node:fs";
import { options } from "./options.mjs";

try {
  const configuration = options(
    {
      name: process.env.INPUT_NAME,
      partition: process.env.INPUT_PARTITION,
      partitions: process.env.INPUT_PARTITIONS,
      arguments: process.env.INPUT_ARGUMENTS,
      directory: process.env["INPUT_WORKING-DIRECTORY"],
      junit: process.env["INPUT_JUNIT-PATH"],
      snapshots: process.env["INPUT_SNAPSHOTS-PATH"],
    },
    process.env.GITHUB_WORKSPACE,
  );
  for (const [name, value] of Object.entries(configuration.outputs)) {
    if (/[\r\n]/.test(value))
      throw new Error("Artifact paths cannot contain newlines");
    appendFileSync(process.env.GITHUB_OUTPUT, `${name}=${value}\n`);
  }
  const result = spawnSync("cargo", configuration.args, {
    cwd: configuration.directory,
    stdio: "inherit",
    env: {
      ...process.env,
      INSTA_UPDATE: "new",
      INSTA_PENDING_DIR: configuration.outputs["snapshots-path"],
    },
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
