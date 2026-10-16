# Build the nested command router

Replace the flat-only CLI dispatch with a data-driven nested command tree in
`library/__main__.py`.

## Scope

- Define the canonical resource hierarchy and map each leaf to the existing
  implementation target. Cover playback, database operations, file/folder
  operations, downloads, links, documents, tables, text, torrents, and tabs.
- Generate nested argparse parsers from the tree instead of hand-writing a
  parser for every path.
- Resolve nested paths to the existing module/function targets so the command
  implementation does not need to be duplicated.
- Add canonical-path enumeration for command counts, usage lookup, and the
  grouped command listing shown by the top-level help.

## Help and errors

- Add group help that lists the valid commands beneath a resource.
- Detect an invalid nested path before dispatch and report the invalid command
  with a useful suggestion when one is close.
- Keep trailing help flags from masking an invalid nested command.
- Preserve the existing flat command dispatch while the nested routes are
  introduced, unless a particular old name is intentionally removed.

## Verification

- Test a leaf command with positional and optional arguments, a command with
  multiple nesting levels, group-level help, and an unknown-command path.
- Confirm the top-level subcommand count and grouped listing are generated
  from the same tree used for dispatch.

