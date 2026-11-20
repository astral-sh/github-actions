#!/usr/bin/env python3
"""Record Docker/Depot calls for the publisher contract tests."""

import json
import os
import sys
from pathlib import Path

command = [Path(sys.argv[0]).name, *sys.argv[1:]]
with open(os.environ["CALLS"], "a") as calls:
    calls.write(json.dumps(command) + "\n")

if command[:2] == ["depot", "pull-token"]:
    print("test-pull-token")
elif command[:2] == ["depot", "push"]:
    pushes = [
        json.loads(line)
        for line in Path(os.environ["CALLS"]).read_text().splitlines()
        if json.loads(line)[:2] == ["depot", "push"]
    ]
    if len(pushes) <= int(os.environ.get("DEPOT_PUSH_FAILURES", "0")):
        raise SystemExit(1)
elif command[:2] == ["docker", "login"]:
    sys.stdin.read()
elif command[0] == "sleep":
    pass
elif command[:4] == ["docker", "buildx", "imagetools", "inspect"]:
    variable = (
        "SAVED_DIGEST"
        if command[4].startswith("registry.depot.dev/")
        else "COPIED_DIGEST"
    )
    print(os.environ.get(variable, os.environ["DIGEST"]))
elif command[:4] == ["docker", "buildx", "imagetools", "create"]:
    metadata = Path(command[command.index("--metadata-file") + 1])
    metadata.write_text(
        json.dumps(
            {"containerimage.descriptor": {"digest": os.environ["FINAL_DIGEST"]}}
        )
    )
else:
    raise SystemExit(f"unexpected command: {command!r}")
