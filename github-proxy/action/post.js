"use strict";

const { validateCapability, validateProxyUrl } = require("./validation.js");

const REVOCATION_TIMEOUT_MS = 30_000;

async function run({
  env = process.env,
  fetchImpl = globalThis.fetch,
  makeTimeoutSignal = (delay) => AbortSignal.timeout(delay),
  warn = console.warn,
} = {}) {
  if (!env.STATE_proxyUrl || !env.STATE_capability) {
    return;
  }
  try {
    const proxyUrl = validateProxyUrl(env.STATE_proxyUrl);
    if (proxyUrl !== validateProxyUrl(env["INPUT_PROXY-URL"])) {
      throw new Error("saved proxy URL does not match the action input");
    }
    const capability = validateCapability(env.STATE_capability);
    const response = await fetchImpl(`${proxyUrl}/session`, {
      method: "DELETE",
      headers: { authorization: `Bearer ${capability}` },
      redirect: "error",
      signal: makeTimeoutSignal(REVOCATION_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`request failed (${response.status})`);
    }
  } catch (error) {
    warn(`Unable to revoke the GitHub proxy capability: ${error.message}`);
  }
}

if (require.main === module) {
  run().catch((error) => console.warn(error.message));
}

module.exports = { run };
