const fs = require("node:fs");
const path = require("node:path");

const [workspace, layout] = process.argv.slice(2);

function createStaleArtifact(target, name, hash) {
  const unit = path.join(target, "build", name, hash);
  const directory =
    layout === "unit"
      ? path.join(unit, "fingerprint")
      : path.join(target, ".fingerprint", `${name}-${hash}`);
  const crate = name.replaceAll("-", "_");
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, `lib-${crate}.json`), "{}");
  const fingerprint = path.join(directory, `lib-${crate}`);
  fs.writeFileSync(fingerprint, "stale");
  fs.utimesSync(fingerprint, 1, 1);
  const artifacts =
    layout === "unit" ? path.join(unit, "out") : path.join(target, "deps");
  fs.mkdirSync(artifacts, { recursive: true });
  fs.writeFileSync(path.join(artifacts, `lib${crate}-${hash}.rlib`), "stale");
}

for (const profile of ["debug", "profiling"]) {
  const target = path.join(workspace, "target", profile);
  createStaleArtifact(target, "workspace-cache-fixture", "1111111111111111");
}
