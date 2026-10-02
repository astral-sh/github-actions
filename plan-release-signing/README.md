# Plan release signing

Read a cargo-dist target inventory, require every macOS and Windows release
target to have a native verification runner, and generate the artifact
declarations shared by release preparation, assembly, and verification.

The caller declares the executable inventory for each wheel package. The
archive package identifies which wheel's executables cargo-dist includes in the
GitHub release archive.

```yaml
- id: signing-plan
  uses: astral-sh/github-actions/plan-release-signing@<commit>
  with:
    archive-package: uv
    packages: >-
      {
        "macos": {"uv": ["uv", "uvx"], "uv_build": ["uv-build"]},
        "windows": {
          "uv": ["uv.exe", "uvx.exe", "uvw.exe"],
          "uv_build": ["uv-build.exe"]
        }
      }
```

The action installs `uv` and reads `dist-workspace.toml` by default. Wheel
directories default to `wheels/<target>`, while GitHub archives default to
`github-archives/<archive-package>-<target>.tar.gz` on macOS and `.zip` on
Windows. These paths can be rooted in different directories with the optional
inputs.

The action provides four JSON outputs:

- `targets`: every cargo-dist release target, for collecting built wheels.
- `artifacts`: the macOS and Windows [artifact declarations](../release-artifacts/README.md).
- `macos`: macOS artifact declarations with native runner and Python architecture.
- `windows`: Windows artifact declarations with native runner and Python architecture.

The native matrices use Astral's macOS runners, Astral's x86 Windows runner,
and GitHub's ARM64 Windows runner. An unknown native target fails planning so a
new release target cannot bypass signing or verification.
