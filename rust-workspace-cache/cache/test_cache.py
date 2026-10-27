import copy
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cache import (
    cache_keys,
    clean,
    installed,
    normalize_manifest,
    restore_binaries,
    source_fingerprint,
    stage_binaries,
    write_installs,
)


class CacheKeyTest(unittest.TestCase):
    def setUp(self):
        self.configuration = {
            "add_job": False,
            "key": "",
            "profiles": ["debug"],
            "workspace_crates": True,
            "cache_bin": True,
            "prefix": "test",
        }
        self.environment = {
            "RUNNER_OS": "Linux",
            "RUNNER_ARCH": "X64",
            "GITHUB_JOB": "build",
        }
        self.lock = {
            "package": [
                {
                    "name": "dep",
                    "version": "1.0.0",
                    "source": "registry+example",
                    "checksum": "one",
                }
            ]
        }

    def keys(
        self,
        compiler="rustc 1.99.0\ncommit-hash: selected",
        source="source-one",
        **changes,
    ):
        configuration = self.configuration | changes
        return cache_keys(
            configuration,
            compiler,
            "cargo 1.99.0",
            [],
            self.lock,
            [],
            self.environment,
            source,
        )

    def test_ignores_toolchain_installation_and_cargo_home(self):
        before = self.keys()
        self.environment.update(
            RUSTUP_HOME="/different/rustup",
            RUSTUP_TOOLCHAIN="1.99.0-x86_64-unknown-linux-gnu",
            CARGO_HOME="/different/cargo",
        )
        self.assertEqual(before, self.keys())

    def test_selected_compiler_and_build_flags_separate_caches(self):
        before = self.keys()
        self.assertNotEqual(before[1], self.keys(compiler="rustc 1.100.0")[1])
        self.environment["RUSTFLAGS"] = "-C target-cpu=znver4"
        self.assertNotEqual(before[1], self.keys()[1])

    def test_dependency_changes_allow_a_compatible_fallback(self):
        before = self.keys()
        self.lock["package"][0]["checksum"] = "two"
        after = self.keys()
        self.assertNotEqual(before[0], after[0])
        self.assertEqual(before[1][-1], after[1][-1])
        self.assertTrue(after[0].startswith(after[1][0]))

    def test_source_changes_refresh_workspace_caches_with_dependency_fallbacks(self):
        before = self.keys()
        after = self.keys(source="source-two")
        self.assertNotEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])
        self.assertTrue(before[0].startswith(after[1][0]))
        self.assertTrue(after[0].startswith(after[1][0]))
        self.assertEqual(after[1][1], after[1][0].removesuffix("-"))
        self.assertEqual(
            self.keys(workspace_crates=False),
            self.keys(workspace_crates=False, source="source-two"),
        )

    def test_workspace_version_changes_do_not_split_dependency_caches(self):
        before = self.keys()
        self.lock["package"].append({"name": "workspace", "version": "2.0.0"})
        self.assertEqual(before, self.keys())
        first = {
            "package": {"name": "workspace", "version": "1.0.0"},
            "dependencies": {"local": {"path": "../local", "version": "1"}},
        }
        second = copy.deepcopy(first)
        second["package"]["version"] = "2.0.0"
        second["dependencies"]["local"] = {"path": "../elsewhere", "version": "2"}
        self.assertEqual(normalize_manifest(first), normalize_manifest(second))

    def test_cache_modes_profiles_and_explicit_keys_are_isolated(self):
        before = self.keys()[1]
        for change in (
            {"workspace_crates": False},
            {"cache_bin": False},
            {"profiles": ["release"]},
            {"key": "different"},
        ):
            with self.subTest(change=change):
                self.assertNotEqual(before, self.keys(**change)[1])

    def test_job_sharing_is_explicit(self):
        shared = self.keys()
        private = self.keys(add_job=True)
        self.environment["GITHUB_JOB"] = "consumer"
        self.assertEqual(shared, self.keys())
        self.assertNotEqual(private, self.keys(add_job=True))


class SourceFingerprintTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)
        self.source = self.root / "src/lib.rs"
        self.source.parent.mkdir()
        self.source.write_text("pub fn example() {}\n")
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)

    def test_changed_tracked_contents_refresh_even_without_staging(self):
        before = source_fingerprint(self.root)
        self.source.write_text("pub fn different() {}\n")
        self.assertNotEqual(before, source_fingerprint(self.root))
        self.source.write_text("pub fn example() {}\n")
        self.assertEqual(before, source_fingerprint(self.root))

    def test_checkout_timestamps_and_untracked_outputs_do_not_refresh(self):
        before = source_fingerprint(self.root)
        os.utime(self.source, (1, 1))
        (self.root / "output").write_text("generated")
        self.assertEqual(before, source_fingerprint(self.root))

    def test_nested_workspaces_include_inputs_elsewhere_in_the_checkout(self):
        before = source_fingerprint(self.source.parent)
        other = self.root / "build-input.txt"
        other.write_text("tracked build input")
        subprocess.run(["git", "add", str(other)], cwd=self.root, check=True)
        self.assertNotEqual(before, source_fingerprint(self.source.parent))
        self.assertEqual(
            source_fingerprint(self.root), source_fingerprint(self.source.parent)
        )

    def test_tracked_path_replaced_by_directory(self):
        before = source_fingerprint(self.root)
        self.source.unlink()
        self.source.mkdir()
        after = source_fingerprint(self.root)
        self.assertNotEqual(before, after)
        (self.source / "untracked.rs").write_text("pub fn generated() {}\n")
        self.assertEqual(after, source_fingerprint(self.root))

    def test_deleted_inputs_refresh(self):
        before = source_fingerprint(self.root)
        self.source.unlink()
        self.assertNotEqual(before, source_fingerprint(self.root))


class CacheContentsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "cargo"
        self.bin = self.home / "bin"
        self.bin.mkdir(parents=True)
        self.stage = self.root / "stage"
        self.lock = self.root / "Cargo.lock"
        self.lock.write_text(
            '[[package]]\nname="dep"\nversion="1.0.0"\nsource="registry+example"\n'
        )
        self.configuration = {
            "cargo_home": str(self.home),
            "workspace_crates": True,
            "binaries": str(self.stage),
            "cache_bin": True,
            "initial_bins": ["rustc", "preinstalled"],
            "target": str(self.root / "target"),
            "profiles": ["debug"],
            "lock": str(self.lock),
        }
        (self.bin / "rustc").write_text("rustup proxy")
        (self.bin / "preinstalled").write_text("runner tool")
        (self.bin / "new-tool").write_text("installed during job")
        write_installs(
            self.home,
            {"old 1": ["preinstalled"], "new 1": ["new-tool"]},
            {"new 1": {"bins": ["new-tool"], "version_req": "*"}},
        )

    def test_stages_only_job_installed_binaries_without_removing_runner_tools(self):
        stage_binaries(self.configuration)
        self.assertEqual(
            sorted(path.name for path in (self.stage / "bin").iterdir()), ["new-tool"]
        )
        self.assertEqual(installed(self.stage)[0], {"new 1": ["new-tool"]})
        self.assertEqual((self.bin / "rustc").read_text(), "rustup proxy")
        self.assertEqual((self.bin / "preinstalled").read_text(), "runner tool")

    def test_restore_merges_install_metadata_and_does_not_replace_existing_tools(self):
        stage_binaries(self.configuration)
        (self.bin / "new-tool").unlink()
        write_installs(self.home, {"old 1": ["preinstalled"]}, {})
        restore_binaries(self.configuration)
        self.assertEqual((self.bin / "new-tool").read_text(), "installed during job")
        self.assertEqual(
            installed(self.home)[0], {"old 1": ["preinstalled"], "new 1": ["new-tool"]}
        )
        (self.bin / "new-tool").write_text("newer runner version")
        restore_binaries(self.configuration)
        self.assertEqual((self.bin / "new-tool").read_text(), "newer runner version")

    def test_cached_binary_names_cannot_escape_the_bin_directory(self):
        write_installs(self.stage, {"bad 1": ["../escape"]}, {})
        with self.assertRaisesRegex(ValueError, "Invalid Cargo binary"):
            restore_binaries(self.configuration)

    def test_disabled_binary_cache_does_not_touch_installations(self):
        self.configuration["cache_bin"] = False
        stage_binaries(self.configuration)
        restore_binaries(self.configuration)
        self.assertFalse(self.stage.exists())
        self.assertTrue((self.bin / "new-tool").is_file())

    def test_cleanup_retains_dependency_sources_and_build_artifacts(self):
        for kind, suffix in [("src", ""), ("cache", ".crate")]:
            directory = self.home / "registry" / kind / "example"
            directory.mkdir(parents=True)
            for name in ["dep-1.0.0", "unused-2.0.0"]:
                path = directory / (name + suffix)
                path.write_text("archive") if suffix else path.mkdir()
        profile = self.root / "target" / "debug"
        for name in ["deps", "build", ".fingerprint", "incremental"]:
            (profile / name).mkdir(parents=True)
        (profile / "final-binary").write_text("output")
        clean(self.configuration)
        self.assertTrue((self.home / "registry/src/example/dep-1.0.0").is_dir())
        self.assertFalse((self.home / "registry/src/example/unused-2.0.0").exists())
        self.assertEqual(
            {path.name for path in profile.iterdir()}, {"deps", "build", ".fingerprint"}
        )

    def test_dependency_only_cleanup_keeps_archives_without_extracted_sources(self):
        self.configuration["workspace_crates"] = False
        source = self.home / "registry/src/example/dep-1.0.0"
        source.mkdir(parents=True)
        (source / "Cargo.toml").write_text("source")
        archive = self.home / "registry/cache/example/dep-1.0.0.crate"
        archive.parent.mkdir(parents=True)
        archive.write_text("archive")
        clean(self.configuration)
        self.assertFalse(source.exists())
        self.assertEqual(archive.read_text(), "archive")

    def test_dependency_only_cleanup_retains_native_dependency_sources(self):
        self.configuration["workspace_crates"] = False
        with Path(self.configuration["lock"]).open("a") as lock:
            lock.write(
                '\n[[package]]\nname="native-sys"\nversion="1.0.0"\n'
                'source="registry+example"\n'
            )
        source = self.home / "registry/src/example/native-sys-1.0.0"
        source.mkdir(parents=True)
        (source / "native.c").write_text("native")
        unused = self.home / "registry/src/example/unused-sys-1.0.0"
        unused.mkdir()
        clean(self.configuration)
        self.assertEqual((source / "native.c").read_text(), "native")
        self.assertFalse(unused.exists())

    def test_cleanup_keeps_host_cross_and_nested_package_profiles(self):
        target = Path(self.configuration["target"])
        profiles = [
            target / "debug",
            target / "wasm32-unknown-unknown/debug",
            target / "package/example/target/debug",
        ]
        for profile in profiles:
            (profile / ".fingerprint").mkdir(parents=True)
            (profile / "deps").mkdir()
            (profile / "deps/libdependency.rlib").write_text("compiled dependency")
            (profile / "incremental").mkdir()
            (profile / "binary").write_text("top-level output")
        (target / "doc").mkdir()
        (target / "doc/index.html").write_text("documentation")
        clean(self.configuration)
        for profile in profiles:
            self.assertEqual(
                (profile / "deps/libdependency.rlib").read_text(), "compiled dependency"
            )
            self.assertFalse((profile / "incremental").exists())
            self.assertFalse((profile / "binary").exists())
        self.assertFalse((target / "doc").exists())


if __name__ == "__main__":
    unittest.main()
