"use strict";

const fs = require("node:fs");
const path = require("node:path");

function validateCatalog(catalog) {
  if (
    !catalog ||
    typeof catalog !== "object" ||
    Array.isArray(catalog) ||
    Object.keys(catalog).length === 0
  ) {
    throw new Error("Runner catalog must be a non-empty object");
  }

  for (const [role, candidates] of Object.entries(catalog)) {
    if (!/^[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*$/.test(role)) {
      throw new Error(`Invalid runner role: ${role}`);
    }
    if (!Array.isArray(candidates) || candidates.length === 0) {
      throw new Error(`Runner role ${role} must have at least one candidate`);
    }
    const labels = new Set();
    for (const candidate of candidates) {
      if (
        !candidate ||
        typeof candidate !== "object" ||
        Array.isArray(candidate) ||
        Object.keys(candidate).sort().join(",") !== "free,label"
      ) {
        throw new Error(
          `Runner candidates for ${role} must contain label and free`,
        );
      }
      if (
        typeof candidate.label !== "string" ||
        candidate.label.trim() !== candidate.label ||
        candidate.label.length === 0 ||
        /[\x00-\x1f\x7f]/.test(candidate.label)
      ) {
        throw new Error(`Invalid runner label for ${role}`);
      }
      if (typeof candidate.free !== "boolean") {
        throw new Error(
          `Runner candidate for ${role} must have a boolean free field`,
        );
      }
      if (labels.has(candidate.label)) {
        throw new Error(`Runner role ${role} repeats label ${candidate.label}`);
      }
      labels.add(candidate.label);
    }
  }
  return catalog;
}

function freeOnlyPolicy(input, owner) {
  if (input === "") {
    if (!owner) {
      throw new Error(
        "GITHUB_REPOSITORY_OWNER is required for automatic selection",
      );
    }
    return owner.toLowerCase() !== "astral-sh";
  }
  if (input === "true") return true;
  if (input === "false") return false;
  throw new Error("free-only must be true or false");
}

function resolveRunners(catalog, { freeOnly, required = [] }) {
  validateCatalog(catalog);
  const runners = Object.fromEntries(
    Object.entries(catalog).flatMap(([role, candidates]) => {
      const candidate = candidates.find(
        (candidate) => !freeOnly || candidate.free,
      );
      return candidate ? [[role, candidate.label]] : [];
    }),
  );

  for (const role of required) {
    if (!Object.hasOwn(catalog, role)) {
      throw new Error(`Unknown required runner role: ${role}`);
    }
    if (!Object.hasOwn(runners, role)) {
      throw new Error(`No eligible runner for required role: ${role}`);
    }
  }
  return runners;
}

function run({ env = process.env } = {}) {
  const freeOnly = freeOnlyPolicy(
    env["INPUT_FREE-ONLY"] || "",
    env.GITHUB_REPOSITORY_OWNER,
  );
  const required = (env.INPUT_REQUIRED || "").split(/\s+/).filter(Boolean);
  const catalog = JSON.parse(
    fs.readFileSync(path.join(__dirname, "runners.json"), "utf8"),
  );
  const runners = resolveRunners(catalog, { freeOnly, required });
  if (!env.GITHUB_OUTPUT) {
    throw new Error("GITHUB_OUTPUT is required");
  }
  fs.appendFileSync(
    env.GITHUB_OUTPUT,
    `runners=${JSON.stringify(runners)}\nfree-only=${freeOnly}\n`,
    "utf8",
  );
}

module.exports = { freeOnlyPolicy, resolveRunners, run, validateCatalog };

if (require.main === module) {
  try {
    run();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
