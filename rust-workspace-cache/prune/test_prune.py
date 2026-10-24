import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from prune import prune_all_workspace_artifacts, prune_workspace_fingerprints

OLD = 1_000_000_000
MARKER = 2_000_000_000
CURRENT = 3_000_000_000


class PruneWorkspaceCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.profile = Path(self.temporary.name)
        (self.profile / ".fingerprint").mkdir()
        (self.profile / "deps").mkdir()
        (self.profile / "build").mkdir()

    def fingerprint(self, package: str, fingerprint: str, timestamp: int) -> Path:
        directory = self.profile / ".fingerprint" / f"{package}-{fingerprint}"
        directory.mkdir()
        (directory / "lib-example.json").write_text("{}")
        stamp = directory / "lib-example"
        stamp.touch()
        os.utime(stamp, ns=(timestamp, timestamp))
        return directory

    def test_removes_superseded_workspace_artifacts(self) -> None:
        old = self.fingerprint("example", "1111111111111111", OLD)
        current = self.fingerprint("example", "2222222222222222", CURRENT)
        dependency = self.fingerprint("dependency", "3333333333333333", OLD)
        unused = self.fingerprint("unused", "4444444444444444", OLD)
        library = self.profile / "deps" / "libexample-1111111111111111.rlib"
        library.touch()
        build = self.profile / "build" / "example-1111111111111111"
        build.mkdir()
        (build / "output").touch()
        active_library = self.profile / "deps" / "libexample-2222222222222222.rlib"
        active_library.touch()

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example", "unused"}),
            (1, 3, 1),
        )
        self.assertFalse(old.exists())
        self.assertFalse(library.exists())
        self.assertFalse(build.exists())
        self.assertTrue(current.is_dir())
        self.assertTrue(active_library.is_file())
        self.assertTrue(dependency.is_dir())
        self.assertTrue(unused.is_dir())

    def test_retains_hashes_used_by_another_active_package(self) -> None:
        old = self.fingerprint("example", "1111111111111111", OLD)
        self.fingerprint("example", "2222222222222222", CURRENT)
        self.fingerprint("dependency", "1111111111111111", CURRENT)

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example"}),
            (0, 0, 2),
        )
        self.assertTrue(old.is_dir())

    def test_refuses_to_prune_without_active_fingerprints(self) -> None:
        old = self.fingerprint("example", "1111111111111111", OLD)
        with self.assertRaisesRegex(RuntimeError, "No active Cargo fingerprints"):
            prune_workspace_fingerprints(self.profile, MARKER, {"example"})
        self.assertTrue(old.is_dir())

    def test_retains_fingerprints_without_usage_metadata(self) -> None:
        unknown = self.fingerprint("example", "1111111111111111", OLD)
        (unknown / "lib-example").unlink()
        self.fingerprint("example", "2222222222222222", MARKER)

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example"}),
            (0, 0, 1),
        )
        self.assertTrue(unknown.is_dir())

    def test_dependency_only_mode_removes_current_and_stale_workspace_artifacts(self):
        old = self.fingerprint("example", "1111111111111111", OLD)
        current = self.fingerprint("example", "2222222222222222", CURRENT)
        dependency = self.fingerprint("dependency", "3333333333333333", OLD)
        library = self.profile / "deps" / "libexample-2222222222222222.rlib"
        library.touch()
        dependency_library = (
            self.profile / "deps" / "libdependency-3333333333333333.rlib"
        )
        dependency_library.touch()
        self.assertEqual(
            prune_all_workspace_artifacts(self.profile, {"example"}, {"example"}), 3
        )
        self.assertFalse(old.exists())
        self.assertFalse(current.exists())
        self.assertFalse(library.exists())
        self.assertTrue(dependency.exists())
        self.assertTrue(dependency_library.exists())

    def test_dependency_only_mode_removes_unhashed_workspace_outputs(self):
        self.fingerprint("example", "1111111111111111", CURRENT)
        outputs = [
            "example.exe",
            "example.pdb",
            "example.dll",
            "example.dll.lib",
            "example.dll.exp",
            "libexample.rlib",
            "libexample.so",
            "example.wasm",
        ]
        for name in outputs:
            (self.profile / "deps" / name).touch()
        dependency = self.profile / "deps" / "dependency.pdb"
        dependency.touch()
        similarly_named = self.profile / "deps" / "example_helper.pdb"
        similarly_named.touch()
        self.assertEqual(
            prune_all_workspace_artifacts(self.profile, {"example"}, {"example"}),
            len(outputs) + 1,
        )
        self.assertTrue(
            all(not (self.profile / "deps" / name).exists() for name in outputs)
        )
        self.assertTrue(dependency.is_file())
        self.assertTrue(similarly_named.is_file())

    def test_dependency_only_mode_uses_target_names_for_unhashed_outputs(self):
        self.fingerprint("example-package", "1111111111111111", CURRENT)
        outputs = ["custom-tool.exe", "custom_tool.pdb", "libcustom_library.rlib"]
        for name in outputs:
            (self.profile / "deps" / name).touch()
        self.assertEqual(
            prune_all_workspace_artifacts(
                self.profile, {"example-package"}, {"custom-tool", "custom_library"}
            ),
            len(outputs) + 1,
        )
        self.assertTrue(
            all(not (self.profile / "deps" / name).exists() for name in outputs)
        )

    @unittest.skipIf(sys.platform == "win32", "Creating symlinks requires privileges")
    def test_removes_stale_symlinks_without_removing_their_targets(self) -> None:
        self.fingerprint("example", "1111111111111111", OLD)
        self.fingerprint("example", "2222222222222222", CURRENT)
        target = self.profile / "keep"
        target.mkdir()
        (target / "output").write_text("keep")
        link = self.profile / "build" / "example-1111111111111111"
        link.symlink_to(target, target_is_directory=True)

        prune_workspace_fingerprints(self.profile, MARKER, {"example"})

        self.assertFalse(link.is_symlink())
        self.assertEqual((target / "output").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
