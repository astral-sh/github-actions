"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { run } = require("./main.cjs");

const commentLabel = "bot:ai-policy-comment";
const closeLabel = "bot:ai-policy-close";
const reminder = `We support using AI (i.e., LLMs) while coding. However, AI **should not** be used to communicate with maintainers.

Please read and follow our [AI policy](https://github.com/astral-sh/.github/blob/main/AI_POLICY.md) when submitting issues and pull requests.
`;

function environment(overrides = {}) {
  return {
    INPUT_TOKEN: "installation-token",
    INPUT_NUMBER: "123",
    INPUT_LABEL: commentLabel,
    GITHUB_REPOSITORY: "astral-sh/uv",
    ...overrides,
  };
}

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function client(responses) {
  const calls = [];
  return {
    calls,
    fetchImpl: async (url, options) => {
      calls.push({
        url,
        ...options,
        body: options.body && JSON.parse(options.body),
      });
      assert.ok(responses.length, "unexpected GitHub request");
      return responses.shift();
    },
  };
}

test("posts the policy reminder without closing the target", async () => {
  const { calls, fetchImpl } = client([
    response({ state: "open", labels: [{ name: commentLabel }] }),
    response({ id: 456 }, 201),
  ]);
  const output = [];
  await run({
    env: environment(),
    fetchImpl,
    log: (value) => output.push(value),
  });

  assert.equal(calls.length, 2);
  assert.equal(
    calls[0].url,
    "https://api.github.com/repos/astral-sh/uv/issues/123",
  );
  assert.equal(calls[0].method, "GET");
  assert.equal(
    calls[1].url,
    "https://api.github.com/repos/astral-sh/uv/issues/123/comments",
  );
  assert.equal(calls[1].method, "POST");
  assert.deepEqual(calls[1].body, { body: reminder });
  assert.equal(calls[1].headers.authorization, "Bearer installation-token");
  assert.ok(
    calls.every(
      (call) => call.redirect === "error" && call.signal instanceof AbortSignal,
    ),
  );
  assert.deepEqual(output, ["::add-mask::installation-token"]);
});

test("comments before closing an issue as not planned", async () => {
  const issue = { state: "open", labels: [{ name: closeLabel }] };
  const { calls, fetchImpl } = client([
    response(issue),
    response({ id: 456 }, 201),
    response(issue),
    response({ state: "closed" }),
  ]);
  await run({
    env: environment({ INPUT_LABEL: closeLabel }),
    fetchImpl,
    log: () => {},
  });

  assert.deepEqual(
    calls.map((call) => call.method),
    ["GET", "POST", "GET", "PATCH"],
  );
  assert.deepEqual(calls[1].body, { body: reminder });
  assert.equal(
    calls[3].url,
    "https://api.github.com/repos/astral-sh/uv/issues/123",
  );
  assert.deepEqual(calls[3].body, {
    state: "closed",
    state_reason: "not_planned",
  });
});

test("closes a pull request through the pulls API", async () => {
  const issue = {
    state: "open",
    labels: [{ name: closeLabel }],
    pull_request: {},
  };
  const { calls, fetchImpl } = client([
    response(issue),
    response({ id: 456 }, 201),
    response(issue),
    response({ state: "closed" }),
  ]);
  await run({
    env: environment({ INPUT_LABEL: closeLabel }),
    fetchImpl,
    log: () => {},
  });

  assert.equal(
    calls[3].url,
    "https://api.github.com/repos/astral-sh/uv/pulls/123",
  );
  assert.deepEqual(calls[3].body, { state: "closed" });
});

test("ignores a removed label or an already closed target", async () => {
  for (const issue of [
    { state: "open", labels: [{ name: commentLabel }] },
    { state: "closed", labels: [{ name: closeLabel }] },
  ]) {
    const { calls, fetchImpl } = client([response(issue)]);
    await run({
      env: environment({ INPUT_LABEL: closeLabel }),
      fetchImpl,
      log: () => {},
    });
    assert.equal(calls.length, 1);
  }
});

test("does not close when the label is removed after commenting", async () => {
  const { calls, fetchImpl } = client([
    response({ state: "open", labels: [{ name: closeLabel }] }),
    response({ id: 456 }, 201),
    response({ state: "open", labels: [] }),
  ]);
  await run({
    env: environment({ INPUT_LABEL: closeLabel }),
    fetchImpl,
    log: () => {},
  });
  assert.equal(calls.length, 3);
});

test("does not close when posting the reminder fails", async () => {
  const { calls, fetchImpl } = client([
    response({ state: "open", labels: [{ name: closeLabel }] }),
    response({ message: "Forbidden" }, 403),
  ]);
  await assert.rejects(
    run({
      env: environment({ INPUT_LABEL: closeLabel }),
      fetchImpl,
      log: () => {},
    }),
    /POST issues\/123\/comments failed \(403\)/,
  );
  assert.equal(calls.length, 2);
});

test("rejects invalid inputs before using the credential", async () => {
  for (const overrides of [
    { INPUT_NUMBER: "0" },
    { INPUT_NUMBER: "../456" },
    { INPUT_NUMBER: "9007199254740993" },
    { INPUT_LABEL: "bot:unrelated" },
    { INPUT_TOKEN: "" },
    { GITHUB_REPOSITORY: "../other" },
    { GITHUB_API_URL: "http://api.example" },
    { GITHUB_API_URL: "https://user@api.example" },
  ]) {
    let called = false;
    await assert.rejects(
      run({
        env: environment(overrides),
        fetchImpl: async () => {
          called = true;
        },
        log: () => {},
      }),
    );
    assert.equal(called, false);
  }
});

test("does not expose the token in a transport error", async () => {
  await assert.rejects(
    run({
      env: environment(),
      fetchImpl: async () => {
        throw new Error("installation-token");
      },
      log: () => {},
    }),
    { message: "GitHub GET issues/123 request failed" },
  );
});
