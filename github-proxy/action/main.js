"use strict";

const { execFileSync } = require("node:child_process");
const { appendFileSync } = require("node:fs");

const { validateCapability, validateProxyUrl } = require("./validation.js");

function fileCommand(file, name, value, appendFile = appendFileSync) {
  if (!file || /[\r\n]/u.test(value)) {
    throw new Error(`invalid GitHub Actions value for ${name}`);
  }
  appendFile(file, `${name}=${value}\n`);
}

function runGit(execFile, arguments_, description) {
  try {
    execFile("git", arguments_);
  } catch {
    throw new Error(`unable to configure the GitHub proxy: ${description}`);
  }
}

function run({
  env = process.env,
  execFile = execFileSync,
  appendFile = appendFileSync,
  write = process.stdout.write.bind(process.stdout),
} = {}) {
  const root = validateProxyUrl(env["INPUT_PROXY-URL"]);
  const capability = validateCapability(env.INPUT_CAPABILITY || "");

  write(`::add-mask::${capability}\n`);
  fileCommand(env.GITHUB_STATE, "proxyUrl", root, appendFile);
  fileCommand(env.GITHUB_STATE, "capability", capability, appendFile);

  const repository = env.INPUT_REPOSITORY || "";
  const repositoryParts = repository.split("/");
  if (repositoryParts.length !== 2 || repositoryParts.some((part, index) => (
    !/^[A-Za-z0-9_.-]+$/u.test(part) ||
    part.length > (index === 0 ? 39 : 100) ||
    part === "." ||
    part === ".."
  ))) {
    throw new Error("repository must be OWNER/REPO");
  }
  const remote = env.INPUT_REMOTE || "origin";
  if (
    !/^[A-Za-z0-9_.-]+$/u.test(remote) ||
    remote.startsWith("-") ||
    remote.startsWith(".") ||
    remote.endsWith(".") ||
    remote.endsWith(".lock") ||
    remote.includes("..")
  ) {
    throw new Error("remote must be a safe Git remote name");
  }

  const gitUrl = `${root}/${repository}.git`;
  const authorizationKey = `http.${gitUrl}.extraheader`;
  runGit(execFile, ["config", "--local", "--replace-all", authorizationKey, ""], "authorization reset");
  runGit(execFile, ["config", "--local", "--add", authorizationKey, `AUTHORIZATION: Bearer ${capability}`], "authorization");
  runGit(execFile, ["config", "--local", `http.${root}/.postBuffer`, "4194304"], "push buffering");
  runGit(execFile, ["remote", "set-url", "--push", remote, gitUrl], "push URL");
  fileCommand(env.GITHUB_OUTPUT, "git-url", gitUrl, appendFile);
}

if (require.main === module) {
  try {
    run();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = { run };
