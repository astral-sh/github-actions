"""Exercise input restoration against Cargo's build-script freshness checks."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import inputs


class CargoInputsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cargo-inputs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "inputs").mkdir()
        (self.root / "Cargo.toml").write_text(
            '[package]\nname = "cache-input-fixture"\nversion = "0.1.0"\nedition = "2021"\n'
        )
        (self.root / "src/main.rs").write_text(
            'include!(concat!(env!("OUT_DIR"), "/generated.rs"));\n'
            'fn main() { println!("{}", VALUE); }\n'
        )
        (self.root / "build.rs").write_text(
            "use std::{env, fs, path::PathBuf};\n"
            "fn main() {\n"
            '    println!("cargo:rerun-if-changed=inputs");\n'
            '    let mut files = fs::read_dir("inputs").unwrap()\n'
            "        .map(|p| p.unwrap().path()).collect::<Vec<_>>();\n"
            "    files.sort();\n"
            "    let value = files.into_iter().map(|p| fs::read_to_string(p).unwrap())\n"
            "        .collect::<String>();\n"
            '    fs::write(PathBuf::from(env::var("OUT_DIR").unwrap()).join("generated.rs"),\n'
            '        format!("const VALUE: &str = {:?};", value)).unwrap();\n'
            "}\n"
        )
        self.value = self.root / "inputs/value.txt"
        self.value.write_text("original")
        (self.root / ".gitignore").write_text("target/\n")
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        self.environment = os.environ | {
            "CARGO_UNSTABLE_CHECKSUM_FRESHNESS": "true",
            "RUSTC_BOOTSTRAP": "1",
            "CARGO_INCREMENTAL": "0",
            "CARGO_TERM_COLOR": "never",
            "CARGO_TARGET_DIR": str(self.root / "target"),
        }
        self.build("original", rebuilt=True)
        self.saved = inputs.scan(self.root)

    def build(self, expected: str, *, rebuilt: bool) -> None:
        result = subprocess.run(
            ["cargo", "run", "--offline", "-vv"],
            cwd=self.root,
            env=self.environment,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout.splitlines()[-1], expected, result.stderr)
        self.assertEqual(
            "Compiling cache-input-fixture" in result.stderr, rebuilt, result.stderr
        )

    def restore(self) -> dict[str, int]:
        return inputs.restore(self.root, self.saved, [self.root / "target/debug"])

    def test_fresh_checkout_reuses_artifacts(self) -> None:
        for group in ["files", "directories"]:
            for name in self.saved[group]:
                os.utime(self.root / name, None)
        result = self.restore()
        self.assertGreater(result["restored_files"], 0)
        self.assertEqual(result["invalidated_build_scripts"], 0)
        self.build("original", rebuilt=False)

    def test_changed_bytes_with_preserved_timestamp_rebuild(self) -> None:
        old = self.value.stat().st_mtime_ns
        self.value.write_text("changed")
        os.utime(self.value, ns=(old, old))
        self.assertEqual(self.restore()["invalidated_build_scripts"], 1)
        staged = subprocess.check_output(
            ["git", "show", ":inputs/value.txt"], cwd=self.root, text=True
        )
        self.assertEqual(staged, "original")
        self.build("changed", rebuilt=True)

    def test_subsequent_checkout_keeps_matching_input_timestamps(self) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "seed",
            ],
            cwd=self.root,
            check=True,
        )
        for name in self.saved["files"]:
            os.utime(self.root / name, None)
        subprocess.run(["git", "update-index", "--refresh"], cwd=self.root, check=True)
        self.restore()
        subprocess.run(
            ["git", "checkout", "--quiet", "--force", "HEAD"], cwd=self.root, check=True
        )
        self.assertEqual(
            self.value.stat().st_mtime_ns,
            self.saved["files"]["inputs/value.txt"]["mtime_ns"],
        )
        self.build("original", rebuilt=False)

    def test_changed_bytes_rebuild_when_cached_output_is_in_the_future(self) -> None:
        future = time.time_ns() + 60_000_000_000
        for output in (self.root / "target/debug/build").glob("*/output"):
            os.utime(output, ns=(future, future))
        old = self.value.stat().st_mtime_ns
        self.value.write_text("changed")
        os.utime(self.value, ns=(old, old))
        self.assertEqual(self.restore()["invalidated_build_scripts"], 1)
        self.build("changed", rebuilt=True)

    def test_new_untracked_input_rebuilds(self) -> None:
        (self.root / "inputs/extra.txt").write_text("extra+")
        self.assertEqual(self.restore()["invalidated_build_scripts"], 1)
        self.build("extra+original", rebuilt=True)

    def test_replaced_untracked_input_keeps_directory_timestamp(self) -> None:
        extra = self.root / "inputs/extra.txt"
        extra.write_text("old+")
        self.build("old+original", rebuilt=True)
        self.saved = inputs.scan(self.root)
        old = extra.stat().st_mtime_ns
        extra.unlink()
        extra.write_text("new+")
        os.utime(extra, ns=(old, old))
        directory = extra.parent
        modified = time.time_ns() + 1_000_000_000
        os.utime(directory, ns=(modified, modified))
        modified = directory.stat().st_mtime_ns
        self.restore()
        self.assertEqual(directory.stat().st_mtime_ns, modified)
        self.build("new+original", rebuilt=True)

    def test_deleted_tracked_input_rebuilds(self) -> None:
        self.value.unlink()
        self.assertEqual(self.restore()["invalidated_build_scripts"], 1)
        self.build("", rebuilt=True)

    def test_git_metadata_is_not_restored(self) -> None:
        head = self.root / ".git/HEAD"
        os.utime(head, ns=(1_000_000_000, 1_000_000_000))
        self.restore()
        self.assertEqual(head.stat().st_mtime_ns, 1_000_000_000)

    def test_rejects_escaping_paths(self) -> None:
        with self.assertRaises(ValueError):
            inputs.safe_path(self.root, "../outside")
        with self.assertRaises(ValueError):
            inputs.safe_path(self.root, str(self.root.parent / "outside"))


if __name__ == "__main__":
    unittest.main()
