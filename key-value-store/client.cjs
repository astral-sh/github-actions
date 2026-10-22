"use strict";

const { randomUUID } = require("node:crypto");
const fs = require("node:fs/promises");
const { constants } = require("node:fs");
const path = require("node:path");

const MAX_VALUE_BYTES = 64 * 1024;
const MAX_JSON_BYTES = 32 * 1024;
const REQUEST_TIMEOUT_MS = 15_000;

class ActionError extends Error {}

function command(name, value, write) {
  const escaped = value.replaceAll("%", "%25").replaceAll("\r", "%0D").replaceAll("\n", "%0A");
  write(`::${name}::${escaped}\n`);
}

function httpsUrl(value, name, allowQuery = false) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new ActionError(`${name} must be an HTTPS URL`);
  }
  if (url.protocol !== "https:" || url.username || url.password || url.hash || (!allowQuery && url.search)) {
    throw new ActionError(`${name} must use HTTPS without credentials, a fragment, or unexpected query parameters`);
  }
  return url;
}

function optionsFromEnvironment(operation, env) {
  const url = httpsUrl(env["INPUT_SERVICE-URL"], "service-url");
  if (url.pathname !== "/") {
    throw new ActionError("service-url must be an HTTPS origin without a path");
  }
  const audience = env.INPUT_AUDIENCE || url.origin;
  if (Buffer.byteLength(audience, "utf8") > 2048 || /\s/u.test(audience)) {
    throw new ActionError("audience must be at most 2048 UTF-8 bytes without whitespace");
  }
  const key = env.INPUT_KEY || "";
  if (key.length < 1 || key.length > 256 || /[^A-Za-z0-9._-]/u.test(key) || key === "." || key === "..") {
    throw new ActionError("key must contain 1-256 ASCII letters, digits, dots, underscores, or hyphens, and cannot be . or ..");
  }
  const file = env.INPUT_PATH || "";
  const value = env.INPUT_VALUE || "";
  if (operation === "put" && file && value) {
    throw new ActionError("path and a nonempty value are mutually exclusive");
  }
  const maskValue = env["INPUT_MASK-VALUE"] || "true";
  if (operation === "get" && !["true", "false"].includes(maskValue)) {
    throw new ActionError("mask-value must be true or false");
  }
  if (operation === "get" && !env.GITHUB_OUTPUT) {
    throw new ActionError("GITHUB_OUTPUT is required");
  }
  return { url, audience, key, file, value, maskValue: maskValue === "true" };
}

async function readValueFile(file) {
  let handle;
  try {
    if (!(await fs.lstat(file)).isFile()) {
      throw new ActionError("path must name a regular file, not a symbolic link");
    }
    handle = await fs.open(file, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    const stat = await handle.stat();
    if (!stat.isFile()) throw new ActionError("path must name a regular file");
    if (stat.size > MAX_VALUE_BYTES) throw new ActionError("value exceeds 65536 bytes");
    const buffer = Buffer.alloc(MAX_VALUE_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, null);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    if (length > MAX_VALUE_BYTES) throw new ActionError("value exceeds 65536 bytes");
    return buffer.subarray(0, length);
  } catch (error) {
    if (error instanceof ActionError) throw error;
    throw new ActionError("could not read the value file");
  } finally {
    await handle?.close();
  }
}

async function requireNewFile(file) {
  try {
    await fs.lstat(file);
  } catch (error) {
    if (error.code === "ENOENT") return;
    throw new ActionError("could not inspect the output path");
  }
  throw new ActionError("the output path must not already exist");
}

async function writeValueFile(file, bytes) {
  let handle;
  try {
    await fs.mkdir(path.dirname(file), { recursive: true });
    handle = await fs.open(file, "wx", 0o600);
    await handle.writeFile(bytes);
  } catch {
    if (handle) {
      await handle.close();
      handle = undefined;
      await fs.unlink(file).catch(() => {});
    }
    throw new ActionError("could not create the output file; it must not already exist");
  } finally {
    await handle?.close();
  }
}

async function request(fetchImpl, url, options, description) {
  try {
    return await fetchImpl(url, {
      ...options,
      redirect: "error",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    throw new ActionError(`${description} request failed`);
  }
}

async function readBody(response, limit, description) {
  const chunks = [];
  let length = 0;
  try {
    const declared = response.headers.get("content-length");
    if (declared !== null && Number(declared) > limit) {
      await response.body?.cancel();
      throw new ActionError(`${description} response exceeds its size limit`);
    }
    if (response.body) {
      for await (const chunk of response.body) {
        length += chunk.length;
        if (length > limit) {
          throw new ActionError(`${description} response exceeds its size limit`);
        }
        chunks.push(Buffer.from(chunk));
      }
    }
  } catch (error) {
    if (error instanceof ActionError) throw error;
    throw new ActionError(`${description} response could not be read`);
  }
  return Buffer.concat(chunks, length);
}

async function expectStatus(response, status, description) {
  if (response.status !== status) {
    await response.body?.cancel().catch(() => {});
    throw new ActionError(`${description} failed (HTTP ${response.status})`);
  }
}

async function requestJson(fetchImpl, url, options, description) {
  const response = await request(fetchImpl, url, options, description);
  await expectStatus(response, 200, description);
  const body = await readBody(response, MAX_JSON_BYTES, description);
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
  } catch {
    throw new ActionError(`${description} response was not valid JSON`);
  }
}

async function exchange(options, env, fetchImpl, write) {
  if (!env.ACTIONS_ID_TOKEN_REQUEST_URL || !env.ACTIONS_ID_TOKEN_REQUEST_TOKEN) {
    throw new ActionError("id-token: write is required to request a GitHub OIDC token");
  }
  if (["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"].some((name) => env[name]) && env.NODE_USE_ENV_PROXY !== "1") {
    throw new ActionError("set NODE_USE_ENV_PROXY=1 when an HTTP proxy is configured");
  }
  const oidcUrl = httpsUrl(env.ACTIONS_ID_TOKEN_REQUEST_URL, "ACTIONS_ID_TOKEN_REQUEST_URL", true);
  oidcUrl.searchParams.set("audience", options.audience);
  const oidc = await requestJson(fetchImpl, oidcUrl, {
    headers: { authorization: `Bearer ${env.ACTIONS_ID_TOKEN_REQUEST_TOKEN}` },
  }, "OIDC token");
  if (typeof oidc?.value !== "string" || oidc.value.length > 16 * 1024 || /\s/u.test(oidc.value) || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/u.test(oidc.value)) {
    throw new ActionError("OIDC response did not contain a valid encoded token");
  }
  command("add-mask", oidc.value, write);
  const session = await requestJson(fetchImpl, new URL("/exchange", options.url), {
    method: "POST",
    headers: { authorization: `Bearer ${oidc.value}` },
  }, "token exchange");
  if (typeof session?.access_token !== "string" || session.access_token.length !== 72 || !/^aghs_kv_[0-9a-f]{64}$/u.test(session.access_token)) {
    throw new ActionError("exchange response did not contain a valid session token");
  }
  command("add-mask", session.access_token, write);
  if (session.token_type !== "Bearer" || !Number.isSafeInteger(session.expires_at) || session.expires_at <= Math.floor(Date.now() / 1000)) {
    throw new ActionError("exchange response contained an invalid or expired session");
  }
  return session.access_token;
}

async function outputs(file, entries, uuid = randomUUID) {
  let content = "";
  for (const [name, value] of entries) {
    const delimiter = `kv_${uuid()}`;
    if (value.includes(delimiter)) throw new ActionError("output contains its generated delimiter");
    content += `${name}<<${delimiter}\n${value}\n${delimiter}\n`;
  }
  try {
    await fs.appendFile(file, content, "utf8");
  } catch {
    throw new ActionError("could not write action outputs");
  }
}

async function run(operation, {
  env = process.env,
  fetchImpl = globalThis.fetch,
  write = process.stdout.write.bind(process.stdout),
  uuid,
} = {}) {
  if (!["get", "put", "delete"].includes(operation)) throw new ActionError("unsupported key-value operation");
  const options = optionsFromEnvironment(operation, env);
  let bytes;
  if (operation === "put") {
    bytes = options.file ? await readValueFile(options.file) : Buffer.from(options.value, "utf8");
    if (bytes.length > MAX_VALUE_BYTES) throw new ActionError("value exceeds 65536 bytes");
  } else if (operation === "get" && options.file) {
    await requireNewFile(options.file);
  }
  const token = await exchange(options, env, fetchImpl, write);
  const response = await request(fetchImpl, new URL(`/kv/${options.key}`, options.url), {
    method: operation.toUpperCase(),
    headers: { authorization: `Bearer ${token}`, ...(operation === "put" && { "content-type": "application/octet-stream" }) },
    ...(operation === "put" && { body: bytes }),
  }, `value ${operation}`);
  if (operation !== "get") {
    await expectStatus(response, 204, `value ${operation}`);
    return;
  }
  if (response.status === 404) {
    await response.body?.cancel();
    await outputs(env.GITHUB_OUTPUT, [["found", "false"], ["value", ""], ["path", ""], ["expires-at", ""]], uuid);
    return;
  }
  await expectStatus(response, 200, "value get");
  const expiresAt = response.headers.get("x-expires-at");
  if (!/^[0-9]+$/u.test(expiresAt || "") || !Number.isSafeInteger(Number(expiresAt)) || Number(expiresAt) <= 0) {
    await response.body?.cancel();
    throw new ActionError("value response did not contain a valid expiry");
  }
  bytes = await readBody(response, MAX_VALUE_BYTES, "value get");
  let value = "";
  if (options.file) {
    await writeValueFile(options.file, bytes);
  } else {
    try {
      value = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    } catch {
      throw new ActionError("value is not UTF-8; use path to retrieve binary values");
    }
    if (value.includes("\0")) throw new ActionError("value contains NUL bytes; use path to retrieve binary values");
    if (options.maskValue && value) command("add-mask", value, write);
  }
  await outputs(env.GITHUB_OUTPUT, [
    ["found", "true"], ["value", value], ["path", options.file ? path.resolve(options.file) : ""], ["expires-at", expiresAt],
  ], uuid);
}

function main(operation) {
  run(operation).catch((error) => {
    const message = error instanceof ActionError ? error.message : "key-value action failed";
    command("error", message, process.stdout.write.bind(process.stdout));
    process.exitCode = 1;
  });
}

module.exports = { run, main, ActionError, MAX_VALUE_BYTES };
