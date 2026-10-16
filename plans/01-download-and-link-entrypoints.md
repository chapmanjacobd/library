# Add download and link entrypoints

Implement the new download flows from the `09de9910` change without copying
the full patch.

## Scope

- Extend the shared argument groups so download commands can opt into
  `--direct`, accept a media type through the profile/database-profile
  options, and avoid exposing extractor-only flags on commands that only
  download.
- Make link extraction parsing aware of download mode. Replace the old
  download flag behavior with the new `no-extract` semantics, and add the
  small helpers that download filtered links or download URLs directly.
- Add a download-side entrypoint for pages whose inner links should be
  extracted by default. Keep direct downloading available as an explicit
  mode.
- Expose the resulting targets for the nested commands:
  `download`, `links download`, and database link downloads.

## Behavior to preserve

- Direct URL downloads should not unexpectedly perform page-link extraction.
- Link-list/page downloads should retain the existing filtering and output
  handling.
- Media type selection should be shared by the normal database-add/update
  paths and the new download paths.
- Existing callers of the underlying download and extraction functions should
  continue to work through the default argument behavior.

## Verification

- Exercise direct download, page link extraction, and downloading links from a
  database/list as separate paths.
- Check that `--direct`, `--media-type`, and `--no-extract` are accepted only
  where appropriate and that the generated help text describes them.

