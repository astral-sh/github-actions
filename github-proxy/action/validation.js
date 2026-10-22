"use strict";

const MAX_CAPABILITY_LENGTH = 8192;

function validateProxyUrl(value) {
  const proxyUrl = new URL(value || "");
  if (
    proxyUrl.protocol !== "https:" ||
    proxyUrl.username ||
    proxyUrl.password ||
    proxyUrl.pathname !== "/" ||
    proxyUrl.search ||
    proxyUrl.hash
  ) {
    throw new Error("proxy-url must be a credential-free HTTPS origin");
  }
  return proxyUrl.origin;
}

function validateCapability(value) {
  if (!/^[A-Za-z0-9_-]+$/u.test(value) || value.length > MAX_CAPABILITY_LENGTH) {
    throw new Error("capability must be an opaque base64url value");
  }
  return value;
}

module.exports = { validateCapability, validateProxyUrl };
