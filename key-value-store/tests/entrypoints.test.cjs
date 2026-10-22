"use strict";

const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const https = require("node:https");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

const certificate = path.join(__dirname, "fixtures", "localhost-cert.pem");

async function fixture(context) {
  const directory = await fs.mkdtemp(path.join(process.env.RUNNER_TEMP || os.tmpdir(), "kv-entrypoint-"));
  context.after(() => fs.rm(directory, { recursive: true, force: true }));
  const values = new Map();
  const issued = new Set();
  const sessions = new Map();
  const requests = [];
  const errors = [];
  let count = 0;
  let redirect;
  let origin;
  const server = https.createServer({
    key: await fs.readFile(path.join(__dirname, "fixtures", "localhost-key.pem")),
    cert: await fs.readFile(certificate),
  }, async (request, response) => {
    try {
      const url = new URL(request.url, origin);
      requests.push({ path: url.pathname, authorization: request.headers.authorization });
      if (url.pathname === redirect) {
        response.writeHead(307, { location: `${origin}/credential-leak` }).end();
        return;
      }
      if (url.pathname === "/token") {
        assert.equal(request.method, "GET");
        assert.equal(request.headers.authorization, "Bearer runner-request-token");
        assert.equal(url.searchParams.get("audience"), origin);
        const oidc = `header.${Buffer.from(String(++count)).toString("base64url")}.signature`;
        issued.add(oidc);
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({ value: oidc }));
        return;
      }
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const body = Buffer.concat(chunks);
      const bearer = request.headers.authorization?.replace(/^Bearer /u, "");
      if (url.pathname === "/exchange") {
        assert.equal(request.method, "POST");
        const exchange = body.length === 0 ? { scope: "context" } : JSON.parse(body.toString("utf8"));
        assert.deepEqual(Object.keys(exchange), ["scope"]);
        const { scope } = exchange;
        assert.ok(["context", "workflow", "run", "run-attempt", "job", "repository"].includes(scope));
        if (body.length !== 0) assert.equal(request.headers["content-type"], "application/json");
        requests.at(-1).scope = scope;
        assert.ok(issued.delete(bearer), "each exchange consumes a fresh OIDC token");
        const session = `aghs_kv_${count.toString(16).padStart(64, "0")}`;
        sessions.set(session, scope);
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({
          access_token: session, token_type: "Bearer", expires_at: Math.floor(Date.now() / 1000) + 300,
          scope,
        }));
        return;
      }
      assert.ok(url.pathname.startsWith("/kv/"), "requests stay on the expected endpoints");
      assert.ok(sessions.has(bearer), "value requests use the session credential");
      const key = `${sessions.get(bearer)}:${url.pathname.slice(4)}`;
      if (request.method === "PUT") {
        assert.equal(request.headers["content-type"], "application/octet-stream");
        values.set(key, body);
        response.writeHead(204).end();
      } else if (request.method === "DELETE") {
        values.delete(key);
        response.writeHead(204).end();
      } else {
        assert.equal(request.method, "GET");
        if (!values.has(key)) {
          response.writeHead(404).end();
        } else {
          response.writeHead(200, { "content-type": "application/octet-stream", "x-expires-at": "2000000000" });
          response.end(values.get(key));
        }
      }
    } catch (error) {
      errors.push(error);
      response.writeHead(500).end();
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `https://127.0.0.1:${server.address().port}`;
  context.after(async () => {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    assert.deepEqual(errors, []);
  });

  async function action(operation, inputs = {}) {
    const output = path.join(directory, `outputs-${count}-${operation}`);
    const env = { ...process.env };
    for (const name of Object.keys(env)) {
      if (/^(INPUT_|ACTIONS_ID_TOKEN_)/iu.test(name) || /^(https?_proxy|all_proxy|no_proxy|node_options)$/iu.test(name)) delete env[name];
    }
    Object.assign(env, {
      NODE_USE_ENV_PROXY: "0",
      NODE_EXTRA_CA_CERTS: certificate,
      ACTIONS_ID_TOKEN_REQUEST_URL: `${origin}/token`,
      ACTIONS_ID_TOKEN_REQUEST_TOKEN: "runner-request-token",
      "INPUT_SERVICE-URL": origin,
      INPUT_KEY: "build.result",
      GITHUB_OUTPUT: output,
      ...inputs,
    });
    const child = spawn(process.execPath, [path.join(__dirname, "..", operation, "main.cjs")], { env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const code = await new Promise((resolve, reject) => {
      child.on("error", reject);
      child.on("close", resolve);
    });
    return { code, stdout, stderr, output };
  }
  return { directory, requests, values, action, redirect: (pathname) => { redirect = pathname; } };
}

async function outputs(file) {
  const text = await fs.readFile(file, "utf8");
  return Object.fromEntries([...text.matchAll(/([^\n]+)<<([^\n]+)\n([\s\S]*?)\n\2\n/gu)].map((match) => [match[1], match[3]]));
}

function succeeded(result) {
  assert.equal(result.code, 0, result.stdout + result.stderr);
  assert.ok(!result.stdout.includes("runner-request-token"));
  assert.ok(result.stdout.split("\n").every((line) => !line || line.startsWith("::add-mask::")));
}

test("action entrypoints use the same requested scope for put, get, and delete", { timeout: 30_000 }, async (context) => {
  const server = await fixture(context);
  succeeded(await server.action("put", { INPUT_SCOPE: "workflow", INPUT_VALUE: "workflow value" }));
  const otherScope = await server.action("get", { INPUT_SCOPE: "job" });
  succeeded(otherScope);
  assert.equal((await outputs(otherScope.output)).found, "false");
  succeeded(await server.action("delete", { INPUT_SCOPE: "job" }));
  const stored = await server.action("get", { INPUT_SCOPE: "workflow" });
  succeeded(stored);
  assert.equal((await outputs(stored.output)).value, "workflow value");
  succeeded(await server.action("delete", { INPUT_SCOPE: "workflow" }));
  const missing = await server.action("get", { INPUT_SCOPE: "workflow" });
  succeeded(missing);
  assert.equal((await outputs(missing.output)).found, "false");
  assert.deepEqual(server.requests.filter((request) => request.path === "/exchange").map((request) => request.scope),
    ["workflow", "job", "job", "workflow", "workflow", "workflow"]);
});

test("real HTTPS action entrypoints round-trip text, binary, empty and missing values", { timeout: 30_000 }, async (context) => {
  const server = await fixture(context);
  const text = " \nπ\r\n::error::stored text\n";
  succeeded(await server.action("put", { INPUT_VALUE: text }));
  const get = await server.action("get");
  succeeded(get);
  assert.deepEqual(await outputs(get.output), { found: "true", value: text, path: "", "expires-at": "2000000000" });
  assert.ok(get.stdout.includes("%0A::error::stored text%0A"));

  const input = path.join(server.directory, "input bytes");
  const output = path.join(server.directory, "nested", "output bytes");
  const binary = Buffer.from([0, 255, 13, 10, 128]);
  await fs.writeFile(input, binary);
  succeeded(await server.action("put", { INPUT_PATH: input }));
  const binaryGet = await server.action("get", { INPUT_PATH: output });
  succeeded(binaryGet);
  assert.deepEqual(await fs.readFile(output), binary);
  assert.equal((await outputs(binaryGet.output)).path, output);

  succeeded(await server.action("put", { INPUT_VALUE: "" }));
  const empty = await server.action("get");
  succeeded(empty);
  assert.equal((await outputs(empty.output)).found, "true");
  assert.equal((await outputs(empty.output)).value, "");
  succeeded(await server.action("delete"));
  const missing = await server.action("get");
  succeeded(missing);
  assert.deepEqual(await outputs(missing.output), { found: "false", value: "", path: "", "expires-at": "" });
  succeeded(await server.action("delete"));
  assert.equal(server.requests.filter((request) => request.path === "/token").length, 9);
  assert.equal(server.requests.filter((request) => request.path === "/exchange").length, 9);
});

test("real HTTPS redirects never forward runner, OIDC or session credentials", { timeout: 30_000 }, async (context) => {
  const server = await fixture(context);
  for (const stage of ["/token", "/exchange", "/kv/build.result"]) {
    server.redirect(stage);
    const result = await server.action("delete");
    assert.equal(result.code, 1);
    assert.match(result.stdout, /::error::.* request failed/u);
    assert.ok(!result.stdout.includes("runner-request-token"));
  }
  assert.ok(server.requests.every((request) => request.path !== "/credential-leak"));
});
