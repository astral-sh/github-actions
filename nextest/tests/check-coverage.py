"""Check that every real platform run covered each fixture test exactly once."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(sys.argv[1])
expected = {f"tests::{name}" for name in ("one", "two", "three", "four")}
for platform, partitions in (("Linux", 1), ("Linux", 2), ("macOS", 2), ("Windows", 2)):
    found = set()
    for partition in range(1, partitions + 1):
        suffix = f"-{partition}" if partitions > 1 else ""
        artifact = root / f"junit-results-fixture-{platform}-{partitions}{suffix}"
        reports = list(artifact.rglob("junit.xml"))
        if len(reports) != 1:
            raise RuntimeError(f"Missing or duplicate JUnit report in {artifact}")
        for case in ET.parse(reports[0]).iter("testcase"):
            if case.find("skipped") is not None:
                continue
            name = case.attrib["name"]
            if (
                case.find("failure") is not None
                or case.find("error") is not None
                or name in found
            ):
                raise RuntimeError(f"Failed or repeated test: {platform} {name}")
            found.add(name)
    if found != expected:
        raise RuntimeError(f"Wrong test coverage on {platform}/{partitions}: {found}")
    print(f"{platform}/{partitions}: all {len(found)} tests ran exactly once")
