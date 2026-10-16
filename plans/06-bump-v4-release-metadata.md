# Bump the v4 release metadata

Finish the breaking CLI restructuring as the 4.0.0 release.

## Scope

- Change the package version in `pyproject.toml` from the 3.x value to
  `4.0.0`.
- Remove `brotab` from the optional/fat dependency set because the `surf`
  command is no longer part of the CLI.
- Regenerate or update `uv.lock` so the lockfile reflects the dependency
  removal and package version.

## Verification

- Confirm the package reports version `4.0.0`.
- Verify the lockfile is consistent with `pyproject.toml` and no longer
  resolves the removed dependency.
- Run the normal package metadata or dependency lock check after all command
  and documentation work has landed.

