# Migrate command names and aliases

Apply the v4 UX naming pass to the command registrations and their usage
surfaces after the router exists.

## Canonical groups

- Put playback actions under `play` and `playback`.
- Put database creation, import, update, merge, search, filesystem, history,
  download, and maintenance actions under `database`.
- Group file, folder, document, archive, table, text, torrent, tabs, links,
  and download operations under their corresponding resources.
- Replace the removed `surf` entrypoint with the supported routes and wire the
  new download/link targets from the preceding plan.

## Registration work

- Update the module command metadata and usage strings to match the canonical
  nested paths.
- Remove collisions where a former flat alias conflicts with a new resource
  path, while retaining useful compatibility aliases for existing commands.
- Add short group aliases such as `db`, `doc`/`docs`, `files`, `fs`, and
  `ls`, plus plural/singular group aliases where the CLI already supports
  them.
- Ensure each nested leaf still reaches the same implementation and receives
  the same arguments and defaults as its flat target.

## Verification

- Add or update CLI contract cases for canonical names, aliases, removed
  names, and representative deeply nested commands.
- Check that usage output and the target function agree for every renamed
  command; do not rely only on parser construction succeeding.

