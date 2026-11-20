"use strict";

const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const { join } = require("node:path");
const test = require("node:test");

const { run: runMain } = require("./main.js");
const { run: runPost } = require("./post.js");
const { validateCapability } = require("./validation.js");

function environment(overrides = {}) {
  return {
    "INPUT_PROXY-URL": "https://proxy.example",
    INPUT_CAPABILITY: "opaque_ciphertext-123",
    INPUT_REPOSITORY: "octo/widgets",
    INPUT_REMOTE: "origin",
    GITHUB_STATE: "state",
    GITHUB_OUTPUT: "output",
    ...overrides,
  };
}

test("configures a credential-free push URL and masks the scoped capability", () => {
  const calls = [];
  const files = new Map();
  const output = [];
  runMain({
    env: environment(),
    execFile: (command, arguments_) => calls.push([command, arguments_]),
    appendFile: (file, value) => files.set(file, `${files.get(file) || ""}${value}`),
    write: (value) => output.push(value),
  });

  assert.deepEqual(calls, [
    ["git", ["config", "--local", "--replace-all", "http.https://proxy.example/octo/widgets.git.extraheader", ""]],
    ["git", ["config", "--local", "--add", "http.https://proxy.example/octo/widgets.git.extraheader", "AUTHORIZATION: Bearer opaque_ciphertext-123"]],
    ["git", ["config", "--local", "http.https://proxy.example/.postBuffer", "4194304"]],
    ["git", ["remote", "set-url", "--push", "origin", "https://proxy.example/octo/widgets.git"]],
  ]);
  assert.deepEqual(output, ["::add-mask::opaque_ciphertext-123\n"]);
  assert.match(files.get("output"), /^git-url=https:\/\/proxy.example\/octo\/widgets.git$/mu);
  assert.doesNotMatch(files.get("output"), /opaque_ciphertext-123/u);
  assert.match(files.get("state"), /^proxyUrl=https:\/\/proxy.example$/mu);
  assert.match(files.get("state"), /^capability=opaque_ciphertext-123$/mu);
});

test("keeps proxy credentials independent for repositories sharing an origin", (context) => {
  const directory = mkdtempSync(join(tmpdir(), "aghs-github-proxy-"));
  context.after(() => rmSync(directory, { recursive: true, force: true }));
  const execFile = (command, arguments_) => execFileSync(command, arguments_, {
    cwd: directory,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_CONFIG_GLOBAL: join(directory, "global.gitconfig"),
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_COUNT: "0",
    },
  });
  const git = (...arguments_) => execFile("git", arguments_).trim();
  git("init", "--quiet");
  git("config", "--local", "http.extraheader", "X-Global: preserved");
  git("config", "--local", "http.https://proxy.example/.extraheader", "X-Origin: preserved");

  const repositories = [
    { remote: "origin", repository: "octo/widgets", capability: "widgets-capability" },
    { remote: "tools", repository: "octo/tools", capability: "tools-capability" },
  ];
  for (const { remote, repository, capability } of repositories) {
    git("remote", "add", remote, `https://github.com/${repository}.git`);
    runMain({
      env: environment({
        INPUT_REMOTE: remote,
        INPUT_REPOSITORY: repository,
        INPUT_CAPABILITY: capability,
        GITHUB_STATE: join(directory, `${remote}.state`),
        GITHUB_OUTPUT: join(directory, `${remote}.output`),
      }),
      execFile,
      write: () => {},
    });
  }

  for (const { remote, repository, capability } of repositories) {
    const gitUrl = `https://proxy.example/${repository}.git`;
    assert.equal(git("remote", "get-url", "--push", remote), gitUrl);
    for (const suffix of ["", "/info/refs?service=git-receive-pack", "/git-receive-pack"]) {
      assert.equal(
        git("config", "--get-urlmatch", "http.extraheader", `${gitUrl}${suffix}`),
        `AUTHORIZATION: Bearer ${capability}`,
      );
    }
    assert.equal(git("config", "--get-urlmatch", "http.postBuffer", gitUrl), "4194304");
  }

  for (const repository of ["octo/unconfigured", "octo/widgets.git-backup"]) {
    assert.equal(
      git("config", "--get-urlmatch", "http.extraheader", `https://proxy.example/${repository}.git`),
      "X-Origin: preserved",
    );
  }
  assert.equal(
    git("config", "--get-urlmatch", "http.extraheader", "https://github.com/octo/widgets.git"),
    "X-Global: preserved",
  );
});

test("records revocation state before Git configuration can fail", () => {
  for (const failingCommand of [0, 1, 2, 3]) {
    const files = new Map();
    let commandCount = 0;

    assert.throws(() => runMain({
      env: environment(),
      execFile: () => {
        if (commandCount++ === failingCommand) {
          throw new Error("Git command failed with opaque_ciphertext-123");
        }
      },
      appendFile: (file, value) => files.set(file, `${files.get(file) || ""}${value}`),
      write: () => {},
    }), (error) => {
      assert.match(error.message, /unable to configure the GitHub proxy/u);
      assert.doesNotMatch(error.message, /opaque_ciphertext-123/u);
      return true;
    });

    assert.match(files.get("state"), /^proxyUrl=https:\/\/proxy.example$/mu);
    assert.match(files.get("state"), /^capability=opaque_ciphertext-123$/mu);
    assert.equal(files.has("output"), false);
  }
});

test("rejects unsafe proxy URLs, repositories, remotes, and capabilities", () => {
  for (const overrides of [
    { "INPUT_PROXY-URL": "http://proxy.example" },
    { "INPUT_PROXY-URL": "https://proxy.example@attacker.example" },
    { "INPUT_PROXY-URL": "https://proxy.example/path" },
    { "INPUT_PROXY-URL": "https://proxy.example//" },
    { "INPUT_PROXY-URL": "https://proxy.example?query=1" },
    { "INPUT_PROXY-URL": "https://proxy.example#fragment" },
    { INPUT_REPOSITORY: "../widgets" },
    { INPUT_REPOSITORY: `${"a".repeat(40)}/widgets` },
    { INPUT_REPOSITORY: `octo/${"a".repeat(101)}` },
    { INPUT_REMOTE: "--upload-pack=evil" },
    { INPUT_REMOTE: "." },
    { INPUT_REMOTE: ".." },
    { INPUT_REMOTE: ".hidden" },
    { INPUT_REMOTE: "origin." },
    { INPUT_REMOTE: "origin..invalid" },
    { INPUT_REMOTE: "origin.lock" },
    { INPUT_CAPABILITY: "bad token" },
    { INPUT_CAPABILITY: "a".repeat(8192 + 1) },
  ]) {
    assert.throws(() => runMain({
      env: environment(overrides),
      execFile: () => {},
      appendFile: () => {},
      write: () => {},
    }));
  }
});

test("limits capabilities to the proxy's encoded capability limit", () => {
  const largestCapability = "a".repeat(8192);
  assert.equal(validateCapability(largestCapability), largestCapability);
  assert.throws(() => validateCapability("a".repeat(8192 + 1)));
});

test("preserves revocation state when repository or remote validation fails", () => {
  for (const overrides of [{ INPUT_REPOSITORY: "../widgets" }, { INPUT_REMOTE: ".." }]) {
    const files = new Map();
    assert.throws(() => runMain({
      env: environment(overrides),
      execFile: () => assert.fail("Git must not run"),
      appendFile: (file, value) => files.set(file, `${files.get(file) || ""}${value}`),
      write: () => {},
    }));
    assert.match(files.get("state"), /^capability=opaque_ciphertext-123$/mu);
  }
});

test("revokes the capability in the agent job post step", async () => {
  const calls = [];
  const signals = [];
  const signal = {};
  await runPost({
    env: {
      "INPUT_PROXY-URL": "https://proxy.example/",
      STATE_proxyUrl: "https://proxy.example",
      STATE_capability: "opaque",
    },
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, status: 204 };
    },
    makeTimeoutSignal: (delay) => {
      signals.push(delay);
      return signal;
    },
  });

  assert.deepEqual(signals, [30_000]);
  assert.deepEqual(calls, [{
    url: "https://proxy.example/session",
    options: {
      method: "DELETE",
      headers: { authorization: "Bearer opaque" },
      redirect: "error",
      signal,
    },
  }]);
});

test("reports revocation failures without failing cleanup", async () => {
  const warnings = [];
  await runPost({
    env: {
      "INPUT_PROXY-URL": "https://proxy.example",
      STATE_proxyUrl: "https://proxy.example",
      STATE_capability: "opaque",
    },
    fetchImpl: async () => ({ ok: false, status: 502 }),
    warn: (message) => warnings.push(message),
  });
  assert.match(warnings[0], /request failed \(502\)/u);
});

test("reports timed out revocation without failing cleanup", async () => {
  const warnings = [];
  await runPost({
    env: {
      "INPUT_PROXY-URL": "https://proxy.example",
      STATE_proxyUrl: "https://proxy.example",
      STATE_capability: "opaque",
    },
    fetchImpl: async () => {
      throw new Error("revocation timed out");
    },
    makeTimeoutSignal: () => ({}),
    warn: (message) => warnings.push(message),
  });
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /revocation timed out/u);
});

test("refuses to send a capability when revocation state is invalid", async () => {
  for (const env of [
    {
      "INPUT_PROXY-URL": "https://proxy.example",
      STATE_proxyUrl: "http://attacker.example",
      STATE_capability: "opaque",
    },
    {
      "INPUT_PROXY-URL": "https://proxy.example",
      STATE_proxyUrl: "https://proxy.example/another-path",
      STATE_capability: "opaque",
    },
    {
      "INPUT_PROXY-URL": "https://proxy.example",
      STATE_proxyUrl: "https://attacker.example",
      STATE_capability: "opaque",
    },
    {
      "INPUT_PROXY-URL": "https://proxy.example",
      STATE_proxyUrl: "https://proxy.example",
      STATE_capability: "bad token",
    },
  ]) {
    const warnings = [];
    await runPost({
      env,
      fetchImpl: () => assert.fail("invalid state must not trigger a request"),
      warn: (message) => warnings.push(message),
    });
    assert.equal(warnings.length, 1);
  }
});

test("skips revocation when setup did not persist complete state", async () => {
  for (const env of [
    {},
    { STATE_proxyUrl: "https://proxy.example" },
    { STATE_capability: "opaque" },
  ]) {
    await runPost({
      env,
      fetchImpl: () => assert.fail("incomplete state must not trigger a request"),
    });
  }
});
