## ty guidance

- Inspect the supplied Ruff submodule range with `git -C ruff log` and `git -C ruff show` for
  `astral-sh/ruff` entries. Use ty's own Git history for `astral-sh/ty` entries.
- Lead with the effect on type checking or editor behavior. Preserve diagnostic names, configuration
  keys, and the conditions under which a diagnostic, inference result, or editor feature changes.
  Respect ty's existing categories, including `Diagnostic improvements`, `LSP server`, and
  `Memory usage improvements`.
- Keep changes visible to ty users, including updated bundled Typeshed stubs. Preserve the repository
  in each PR link, even when a ty and Ruff pull request have the same number. Preserve any Typeshed
  comparison link attached to a retained entry.
