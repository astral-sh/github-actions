#!/usr/bin/env bash
set -euo pipefail

codex_home="${1:?Codex home directory is required}"

mkdir -p "$RUNNER_TEMP/codex-security"
curl --fail --location --silent --show-error \
  --output "$RUNNER_TEMP/codex.tar.gz" \
  https://github.com/openai/codex/releases/download/rust-v0.171.0/codex-x86_64-unknown-linux-musl.tar.gz
printf '%s  %s\n' \
  01baa2e47809f8597be5b2f8abd4e4dfe3fb5bcb6e504c2fbaaad97056c15e8d \
  "$RUNNER_TEMP/codex.tar.gz" | sha256sum --check
tar --extract --gzip --file "$RUNNER_TEMP/codex.tar.gz" --directory "$RUNNER_TEMP"
codex="$RUNNER_TEMP/codex-x86_64-unknown-linux-musl"

marketplace=.codex-security-plugin/.agents/plugins/marketplace.json
jq '.name = "openai-curated-ci" | .plugins |= map(select(.name == "codex-security"))' \
  "$marketplace" > "$RUNNER_TEMP/marketplace.json"
mv "$RUNNER_TEMP/marketplace.json" "$marketplace"

CODEX_HOME="$codex_home" "$codex" plugin marketplace add \
  "$GITHUB_WORKSPACE/.codex-security-plugin"
CODEX_HOME="$codex_home" "$codex" plugin add \
  codex-security@openai-curated-ci
