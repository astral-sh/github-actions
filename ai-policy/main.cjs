"use strict";

const COMMENT = `We support using AI (i.e., LLMs) while coding. However, AI **should not** be used to communicate with maintainers.

Please read and follow our [AI policy](https://github.com/astral-sh/.github/blob/main/AI_POLICY.md) when submitting issues and pull requests.
`;

async function run({
  env = process.env,
  fetchImpl = globalThis.fetch,
  log = console.log,
} = {}) {
  const token = env.INPUT_TOKEN;
  const number = env.INPUT_NUMBER;
  const label = env.INPUT_LABEL;
  const repository = env.GITHUB_REPOSITORY;
  if (!token) {
    throw new Error("token is required");
  }
  if (
    !/^[1-9][0-9]*$/.test(number || "") ||
    !Number.isSafeInteger(Number(number))
  ) {
    throw new Error("number must be a positive integer");
  }
  if (label !== "bot:ai-policy-comment" && label !== "bot:ai-policy-close") {
    throw new Error(
      "label must be bot:ai-policy-comment or bot:ai-policy-close",
    );
  }
  if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/.test(repository || "")) {
    throw new Error("GITHUB_REPOSITORY must identify the workflow repository");
  }

  const api = new URL(env.GITHUB_API_URL || "https://api.github.com");
  if (
    api.protocol !== "https:" ||
    api.username ||
    api.password ||
    api.search ||
    api.hash
  ) {
    throw new Error(
      "GITHUB_API_URL must be an HTTPS URL without credentials, query, or fragment",
    );
  }
  log(
    `::add-mask::${token.replaceAll("%", "%25").replaceAll("\r", "%0D").replaceAll("\n", "%0A")}`,
  );

  async function request(method, path, body) {
    let response;
    try {
      response = await fetchImpl(
        `${api.href.replace(/\/$/, "")}/repos/${repository}/${path}`,
        {
          method,
          headers: {
            authorization: `Bearer ${token}`,
            accept: "application/vnd.github+json",
            "content-type": "application/json",
            "user-agent": "astral-sh-ai-policy",
            "x-github-api-version": "2022-11-28",
          },
          body: body === undefined ? undefined : JSON.stringify(body),
          redirect: "error",
          signal: AbortSignal.timeout(30_000),
        },
      );
    } catch {
      throw new Error(`GitHub ${method} ${path} request failed`);
    }
    if (!response.ok) {
      throw new Error(`GitHub ${method} ${path} failed (${response.status})`);
    }
    return response.json();
  }

  function isActive(issue) {
    return (
      issue.state === "open" && issue.labels.some((item) => item.name === label)
    );
  }

  const issue = await request("GET", `issues/${number}`);
  if (!isActive(issue)) {
    log(
      "Skipping: the issue or pull request is closed or the policy label was removed.",
    );
    return;
  }

  await request("POST", `issues/${number}/comments`, { body: COMMENT });
  if (label === "bot:ai-policy-close") {
    const current = await request("GET", `issues/${number}`);
    if (!isActive(current)) {
      log(
        "Skipping closure: the issue or pull request is closed or the policy label was removed.",
      );
      return;
    }
    if (current.pull_request) {
      await request("PATCH", `pulls/${number}`, { state: "closed" });
    } else {
      await request("PATCH", `issues/${number}`, {
        state: "closed",
        state_reason: "not_planned",
      });
    }
  }
}

if (require.main === module) {
  run().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { run };
