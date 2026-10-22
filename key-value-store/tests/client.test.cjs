"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");
const { run, MAX_VALUE_BYTES } = require("../client.cjs");

const token = `aghs_kv_${"a".repeat(64)}`;
const oidc = "header.payload.signature";

function environment(overrides = {}) {
  return {
    "INPUT_SERVICE-URL": "https://kv.example/",
    INPUT_KEY: "build.result",
    ACTIONS_ID_TOKEN_REQUEST_URL: "https://issuer.example/token?job=123&audience=old",
    ACTIONS_ID_TOKEN_REQUEST_TOKEN: "runner-token",
    ...overrides,
  };
}

function session(scope) {
  return new Response(JSON.stringify({
    access_token: token, token_type: "Bearer", expires_at: Math.floor(Date.now() / 1000) + 300,
    scope,
  }));
}

function mock(operationResponse, overrides = {}) {
  const calls = [];
  const masks = [];
  const responses = [new Response(JSON.stringify({ value: oidc })), session(overrides.INPUT_SCOPE), operationResponse];
  return {
    calls, masks,
    options: {
      env: environment(overrides),
      write: (line) => masks.push(line),
      fetchImpl: async (url, options) => {
        calls.push({ url: String(url), ...options });
        assert.ok(responses.length, "unexpected request or retry");
        return responses.shift();
      },
    },
  };
}

async function outputFile(context) {
  const directory = await fs.mkdtemp(path.join(process.env.RUNNER_TEMP || os.tmpdir(), "kv-test-"));
  context.after(() => fs.rm(directory, { recursive: true, force: true }));
  return { directory, output: path.join(directory, "outputs") };
}

async function outputs(file) {
  const text = await fs.readFile(file, "utf8");
  const result = {};
  let offset = 0;
  while (offset < text.length) {
    const end = text.indexOf("\n", offset);
    const [name, delimiter] = text.slice(offset, end).split("<<");
    const boundary = `\n${delimiter}\n`;
    const next = text.indexOf(boundary, end + 1);
    assert.ok(next >= 0, "output delimiter is present");
    result[name] = text.slice(end + 1, next);
    offset = next + boundary.length;
  }
  return result;
}

function valueResponse(body, expiresAt = 2000000000) {
  return new Response(body, { headers: { "x-expires-at": String(expiresAt) } });
}

test("put exchanges a fresh OIDC token and preserves UTF-8 whitespace and empty values", async () => {
  for (const value of ["", " \nπ\r\n "]) {
    const fixture = mock(new Response(null, { status: 204 }), { INPUT_VALUE: value });
    await run("put", fixture.options);
    assert.equal(fixture.calls.length, 3);
    const url = new URL(fixture.calls[0].url);
    assert.equal(url.searchParams.get("job"), "123");
    assert.equal(url.searchParams.get("audience"), "https://kv.example");
    assert.equal(url.searchParams.getAll("audience").length, 1);
    assert.equal(fixture.calls[0].headers.authorization, "Bearer runner-token");
    assert.equal(fixture.calls[1].url, "https://kv.example/exchange");
    assert.equal(fixture.calls[1].headers.authorization, `Bearer ${oidc}`);
    assert.equal(fixture.calls[1].body, undefined);
    assert.equal(fixture.calls[2].url, "https://kv.example/kv/build.result");
    assert.equal(fixture.calls[2].method, "PUT");
    assert.equal(fixture.calls[2].headers.authorization, `Bearer ${token}`);
    assert.deepEqual(fixture.calls[2].body, Buffer.from(value));
    for (const call of fixture.calls) {
      assert.equal(call.redirect, "error");
      assert.ok(call.signal instanceof AbortSignal);
    }
    assert.deepEqual(fixture.masks, [`::add-mask::${oidc}\n`, `::add-mask::${token}\n`]);
  }
});

test("custom audience is sent only to the OIDC issuer", async () => {
  const fixture = mock(new Response(null, { status: 204 }), { INPUT_AUDIENCE: "urn:astral:kv" });
  await run("delete", fixture.options);
  assert.equal(new URL(fixture.calls[0].url).searchParams.get("audience"), "urn:astral:kv");
  assert.equal(fixture.calls[2].method, "DELETE");
  assert.equal(fixture.calls[2].body, undefined);
});

test("invalid endpoints, namespace selectors, keys, and options fail before credentials are requested", async () => {
  for (const overrides of [
    { "INPUT_SERVICE-URL": "http://kv.example" },
    { "INPUT_SERVICE-URL": "https://user:password@kv.example" },
    { "INPUT_SERVICE-URL": "https://kv.example/prefix" },
    { "INPUT_SERVICE-URL": "https://kv.example?namespace=other" },
    { "INPUT_SERVICE-URL": "https://kv.example/#fragment" },
    { INPUT_KEY: ".." }, { INPUT_KEY: "other/key" }, { INPUT_KEY: "a%2Fb" },
    { INPUT_KEY: "key\n" }, { INPUT_KEY: "key?namespace=other" }, { INPUT_KEY: "a".repeat(257) },
    { INPUT_AUDIENCE: "has spaces" }, { INPUT_AUDIENCE: "🚀".repeat(513) },
    { INPUT_VALUE: "value", INPUT_PATH: "file" },
    { INPUT_SCOPE: "Job" }, { INPUT_SCOPE: "job/other" }, { INPUT_SCOPE: " job" },
  ]) {
    const fixture = mock(undefined, overrides);
    await assert.rejects(run("put", fixture.options));
    assert.equal(fixture.calls.length, 0);
  }
});

test("scopes are requested during exchange and never become caller-selected namespace identifiers", async () => {
  for (const scope of ["workflow", "run", "run-attempt", "job", "repository"]) {
    const fixture = mock(new Response(null, { status: 204 }), { INPUT_SCOPE: scope });
    await run("delete", fixture.options);
    assert.deepEqual(JSON.parse(fixture.calls[1].body), { scope });
    assert.equal(fixture.calls[1].headers["content-type"], "application/json");
    assert.equal(fixture.calls[2].url, "https://kv.example/kv/build.result");
    assert.equal(fixture.calls[2].body, undefined);
  }
});

test("missing or mismatched scope confirmation never reaches the value API", async () => {
  for (const [requested, confirmed] of [["job", undefined], ["job", "context"], ["job", "repository"], ["context", "job"]]) {
    let calls = 0;
    await assert.rejects(run("delete", {
      env: environment({ INPUT_SCOPE: requested }), write: () => {},
      fetchImpl: async () => ++calls === 1
        ? new Response(JSON.stringify({ value: oidc }))
        : session(confirmed),
    }), /did not confirm the requested scope/);
    assert.equal(calls, 2);
  }
});

test("a denied scope is never retried with context or another scope", async () => {
  const calls = [];
  await assert.rejects(run("put", {
    env: environment({ INPUT_SCOPE: "repository", INPUT_VALUE: "value" }), write: () => {},
    fetchImpl: async (url, options) => {
      calls.push({ url: String(url), ...options });
      return calls.length === 1
        ? new Response(JSON.stringify({ value: oidc }))
        : new Response(null, { status: 403 });
    },
  }), /token exchange failed \(HTTP 403\)/);
  assert.equal(calls.length, 2);
  assert.deepEqual(JSON.parse(calls[1].body), { scope: "repository" });
});

test("missing OIDC permission and unsafe issuer URLs fail before network access", async () => {
  for (const overrides of [
    { ACTIONS_ID_TOKEN_REQUEST_TOKEN: "" },
    { ACTIONS_ID_TOKEN_REQUEST_URL: "http://issuer.example/token" },
    { ACTIONS_ID_TOKEN_REQUEST_URL: "https://user:pass@issuer.example/token" },
    { HTTPS_PROXY: "http://proxy.example" },
  ]) {
    const fixture = mock(undefined, overrides);
    await assert.rejects(run("delete", fixture.options));
    assert.equal(fixture.calls.length, 0);
  }
});

test("writes reject oversized text and files before requesting credentials", async (context) => {
  const { directory } = await outputFile(context);
  const file = path.join(directory, "large");
  await fs.writeFile(file, Buffer.alloc(MAX_VALUE_BYTES + 1));
  for (const overrides of [{ INPUT_VALUE: "π".repeat(MAX_VALUE_BYTES) }, { INPUT_PATH: file }, { INPUT_PATH: directory }]) {
    const fixture = mock(undefined, overrides);
    await assert.rejects(run("put", fixture.options));
    assert.equal(fixture.calls.length, 0);
  }
  await fs.writeFile(file, Buffer.alloc(MAX_VALUE_BYTES, 255));
  const fixture = mock(new Response(null, { status: 204 }), { INPUT_PATH: file });
  await run("put", fixture.options);
  assert.deepEqual(fixture.calls[2].body, Buffer.alloc(MAX_VALUE_BYTES, 255));
});

test("get preserves multiline values and escapes workflow commands while masking", async (context) => {
  const { output } = await outputFile(context);
  const value = "\uFEFF \r\n::error::untrusted\n100%\n";
  const fixture = mock(valueResponse(value), { GITHUB_OUTPUT: output });
  await run("get", fixture.options);
  assert.deepEqual(await outputs(output), { found: "true", value, path: "", "expires-at": "2000000000" });
  assert.ok(fixture.masks[2].includes("%0D%0A::error::untrusted%0A100%25%0A"));
  assert.equal(fixture.masks[2].split("\n").length, 2);
  const text = await fs.readFile(output, "utf8");
  assert.ok(!text.includes(token));
  assert.ok(!text.includes(oidc));
});

test("get distinguishes a missing key from an empty value without writing a missing file", async (context) => {
  const { directory, output } = await outputFile(context);
  const file = path.join(directory, "not-created");
  await run("get", mock(new Response("not found", { status: 404 }), { GITHUB_OUTPUT: output, INPUT_PATH: file }).options);
  assert.deepEqual(await outputs(output), { found: "false", value: "", path: "", "expires-at": "" });
  await assert.rejects(fs.stat(file), { code: "ENOENT" });
  await fs.unlink(output);
  await run("get", mock(valueResponse(""), { GITHUB_OUTPUT: output }).options);
  assert.equal((await outputs(output)).found, "true");
});

test("binary reads require a new file and never produce a text value", async (context) => {
  const { directory, output } = await outputFile(context);
  const file = path.join(directory, "nested", "value");
  const bytes = Buffer.from([0, 255, 13, 10, 42]);
  await run("get", mock(valueResponse(bytes), { GITHUB_OUTPUT: output, INPUT_PATH: file }).options);
  assert.deepEqual(await fs.readFile(file), bytes);
  assert.deepEqual(await outputs(output), { found: "true", value: "", path: file, "expires-at": "2000000000" });
  const fixture = mock(undefined, { GITHUB_OUTPUT: output, INPUT_PATH: file });
  await assert.rejects(run("get", fixture.options), /must not already exist/);
  assert.equal(fixture.calls.length, 0);
  assert.deepEqual(await fs.readFile(file), bytes);
});

test("binary or NUL-containing values cannot silently corrupt text outputs", async (context) => {
  const { output } = await outputFile(context);
  for (const bytes of [Buffer.from([255]), Buffer.from([0]), Buffer.from([0xc3])]) {
    await assert.rejects(run("get", mock(valueResponse(bytes), { GITHUB_OUTPUT: output }).options), /use path/);
    await assert.rejects(fs.stat(output), { code: "ENOENT" });
  }
});

test("masking can be explicitly disabled for nonsensitive text outputs", async (context) => {
  const { output } = await outputFile(context);
  const fixture = mock(valueResponse("visible"), { GITHUB_OUTPUT: output, "INPUT_MASK-VALUE": "false" });
  await run("get", fixture.options);
  assert.equal(fixture.masks.length, 2);
  assert.equal((await outputs(output)).value, "visible");
});

test("oversized and malformed responses fail without emitting values or response bodies", async (context) => {
  const { output } = await outputFile(context);
  for (const response of [
    valueResponse(Buffer.alloc(MAX_VALUE_BYTES + 1)),
    new Response("private response", { headers: { "x-expires-at": "bad" } }),
    new Response("private response", { status: 500 }),
    new Response("private response", { headers: { "x-expires-at": "1", "content-length": String(MAX_VALUE_BYTES + 1) } }),
  ]) {
    const fixture = mock(response, { GITHUB_OUTPUT: output });
    await assert.rejects(run("get", fixture.options), (error) => !error.message.includes("private response"));
    await assert.rejects(fs.stat(output), { code: "ENOENT" });
    assert.equal(fixture.calls.length, 3);
  }
});

test("malformed or expired exchange responses never reach the value API", async () => {
  for (const body of [
    null,
    { access_token: "untrusted\n::error::injection" },
    { access_token: `${token}\n` },
    { access_token: token, token_type: "other", expires_at: 2000000000 },
    { access_token: token, token_type: "Bearer", expires_at: 1 },
  ]) {
    let calls = 0;
    await assert.rejects(run("delete", {
      env: environment(), write: () => {},
      fetchImpl: async () => ++calls === 1
        ? new Response(JSON.stringify({ value: oidc }))
        : new Response(JSON.stringify(body)),
    }));
    assert.equal(calls, 2);
  }
});

test("transport errors are sanitized and ambiguous writes are not retried", async () => {
  let calls = 0;
  await assert.rejects(run("put", {
    env: environment(), write: () => {},
    fetchImpl: async () => {
      calls += 1;
      if (calls === 1) return new Response(JSON.stringify({ value: oidc }));
      if (calls === 2) return session();
      throw new Error(`private ${token}`);
    },
  }), { message: "value put request failed" });
  assert.equal(calls, 3);
});

test("output delimiter collisions fail instead of injecting another output", async (context) => {
  const { output } = await outputFile(context);
  const fixture = mock(valueResponse("\nkv_fixed\nforged=true"), { GITHUB_OUTPUT: output });
  await assert.rejects(run("get", { ...fixture.options, uuid: () => "fixed" }), /delimiter/);
  await assert.rejects(fs.stat(output), { code: "ENOENT" });
});
