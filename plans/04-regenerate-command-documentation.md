# Regenerate command documentation

Refresh the checked-in command reference after the nested command tree and
usage metadata are final.

## Scope

- Regenerate `.github/README.md` so its command index, count, headings,
  examples, and per-command usage blocks use canonical v4 paths.
- Update examples that demonstrate renamed commands, especially filesystem
  database creation, media playback, video ingestion, database merges,
  downloads, and tab opening.
- Document the new resource hierarchy and the short aliases without dumping
  an implementation diff into the README.
- Keep the generated output synchronized with the CLI help/usage source rather
  than hand-editing individual command sections.

## Verification

- Compare the generated reference against the output of the repository's
  README/help generation path.
- Search for stale examples of removed flat names and for missing examples of
  the new nested download and database routes.

