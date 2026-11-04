"use strict";

const fs = require("node:fs");
const inventory = require("./runners.json");
const defaultRoles = require("./roles.json");

const labels = new Set(Object.values(inventory).flat());
const freeLabels = new Set(inventory["github-standard"]);

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

function resolveRunners({ freeOnly, required = [], roles = {} }) {
  if (!roles || typeof roles !== "object" || Array.isArray(roles)) {
    throw new Error(
      "roles must be a JSON object mapping role names to runner labels",
    );
  }
  const candidatesByRole = { ...defaultRoles, ...roles };
  const runners = {};
  for (const [role, candidates] of Object.entries(candidatesByRole)) {
    if (!/^[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*$/.test(role)) {
      throw new Error(`Invalid runner role: ${JSON.stringify(role)}`);
    }
    if (!Array.isArray(candidates) || candidates.length === 0) {
      throw new Error(`Runner role ${role} must have at least one candidate`);
    }
    for (const label of candidates) {
      if (!labels.has(label)) {
        throw new Error(
          `Unknown runner label for ${role}: ${JSON.stringify(label)}`,
        );
      }
    }
    if (new Set(candidates).size !== candidates.length) {
      throw new Error(`Runner role ${role} repeats a candidate`);
    }
    const selected = candidates.find(
      (label) => !freeOnly || freeLabels.has(label),
    );
    if (selected !== undefined) runners[role] = selected;
  }
  for (const role of required) {
    if (!Object.hasOwn(candidatesByRole, role)) {
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
  const roles = JSON.parse(env.INPUT_ROLES || "{}");
  const runners = resolveRunners({ freeOnly, required, roles });
  if (!env.GITHUB_OUTPUT) {
    throw new Error("GITHUB_OUTPUT is required");
  }
  fs.appendFileSync(
    env.GITHUB_OUTPUT,
    `runners=${JSON.stringify(runners)}\nfree-only=${freeOnly}\n`,
    "utf8",
  );
}

module.exports = { freeOnlyPolicy, resolveRunners, run };

if (require.main === module) {
  try {
    run();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
