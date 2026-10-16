# v4 CLI change plan

This is a bite-sized implementation outline for the changes on the `v4-cli`
branch. It follows the intent of the branch commits rather than reproducing
their full diffs.

## Suggested order

1. Add the download/link entrypoints and option plumbing.
2. Define the nested resource command tree and route it to the existing
   command implementations.
3. Update command registrations, aliases, usage text, and CLI contract
   coverage for the new names.
4. Refresh the generated README and make the small documentation wording
   fixes.
5. Bump the package to 4.0.0 and remove the obsolete `brotab` extra.

The first three steps are the functional work. Documentation should be
regenerated after the command tree is stable, and the release metadata should
be changed last.

## Main branch themes

- Make direct downloads, link extraction, and downloads from link lists
  separate, composable CLI flows.
- Organize the large flat command list under resource-oriented groups such as
  `database`, `file`, `folder`, `links`, `play`, `playback`, `table`, and
  `text`.
- Keep a practical alias layer (`db`, `doc`, `docs`, `files`, `fs`, and
  similar short forms) while presenting canonical nested paths in help.
- Update examples and generated command reference text to teach the new
  interface.
- Treat the restructuring as a breaking major release.

