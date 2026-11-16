import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from prune import prune_workspace_fingerprints

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

    def unit(self, package: str, fingerprint: str, timestamp: int) -> Path:
        unit = self.profile / "build" / package / fingerprint
        directory = unit / "fingerprint"
        directory.mkdir(parents=True)
        (directory / "lib-example.json").write_text("{}")
        stamp = directory / "lib-example"
        stamp.touch()
        os.utime(stamp, ns=(timestamp, timestamp))
        (unit / "out").mkdir()
        (unit / "out" / "artifact").write_text("artifact")
        return unit

    def test_prunes_cargo_1_100_workspace_units(self) -> None:
        (self.profile / ".fingerprint").rmdir()
        old = self.unit("example", "1111111111111111", OLD)
        current = self.unit("example", "2222222222222222", CURRENT)
        dependency = self.unit("dependency", "3333333333333333", OLD)
        unused = self.unit("unused", "4444444444444444", OLD)
        unknown = self.unit("example", "5555555555555555", OLD)
        (unknown / "fingerprint" / "lib-example").unlink()
        malformed = self.profile / "build" / "example" / "not-a-hash"
        malformed.mkdir()

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example", "unused"}),
            (1, 1, 1),
        )
        self.assertFalse(old.exists())
        for retained in (current, dependency, unused, unknown, malformed):
            self.assertTrue(retained.is_dir())

    def test_retains_colliding_dependency_and_active_hashes_across_layouts(self) -> None:
        old = self.unit("example", "1111111111111111", OLD)
        self.unit("example", "2222222222222222", CURRENT)
        dependency = self.fingerprint("dependency", "1111111111111111", OLD)
        other_old = self.fingerprint("example", "3333333333333333", OLD)
        active = self.unit("dependency", "3333333333333333", CURRENT)

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example"}),
            (0, 0, 2),
        )
        for retained in (old, dependency, other_old, active):
            self.assertTrue(retained.is_dir())

    def test_retains_dependency_package_named_like_a_legacy_build_unit(self) -> None:
        self.unit("example", "1111111111111111", OLD)
        self.unit("example", "2222222222222222", CURRENT)
        dependency = self.unit("example-1111111111111111", "3333333333333333", OLD)

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example"}),
            (1, 1, 1),
        )
        self.assertTrue(dependency.is_dir())

    def test_does_not_apply_legacy_cleanup_to_cargo_1_100_hashes(self) -> None:
        self.unit("example", "1111111111111111", OLD)
        self.unit("example", "2222222222222222", CURRENT)
        ambiguous = self.profile / "build" / "example-1111111111111111"
        ambiguous.mkdir()
        dependency = self.profile / "deps" / "libdependency-1111111111111111.rlib"
        dependency.touch()

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example"}),
            (1, 1, 1),
        )
        self.assertTrue(ambiguous.is_dir())
        self.assertTrue(dependency.is_file())

    def test_refuses_to_prune_cargo_1_100_without_active_units(self) -> None:
        old = self.unit("example", "1111111111111111", OLD)
        with self.assertRaisesRegex(RuntimeError, "No active Cargo fingerprints"):
            prune_workspace_fingerprints(self.profile, MARKER, {"example"})
        self.assertTrue(old.is_dir())

    @unittest.skipIf(sys.platform == "win32", "Creating symlinks requires privileges")
    def test_does_not_follow_cargo_1_100_symlink_nodes(self) -> None:
        self.unit("example", "2222222222222222", CURRENT)
        target = self.profile / "keep"
        target.mkdir()
        (target / "sentinel").write_text("keep")
        package = self.profile / "build" / "linked-package"
        package.symlink_to(target, target_is_directory=True)
        unit = self.profile / "build" / "example" / "1111111111111111"
        unit.symlink_to(target, target_is_directory=True)
        fingerprint = self.profile / "build" / "example" / "3333333333333333"
        fingerprint.mkdir()
        (fingerprint / "fingerprint").symlink_to(target, target_is_directory=True)

        self.assertEqual(
            prune_workspace_fingerprints(self.profile, MARKER, {"example", "linked-package"}),
            (0, 0, 1),
        )
        self.assertTrue(package.is_symlink())
        self.assertTrue(unit.is_symlink())
        self.assertTrue((fingerprint / "fingerprint").is_symlink())
        self.assertEqual((target / "sentinel").read_text(), "keep")

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
