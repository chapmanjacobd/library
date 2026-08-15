# Feature Review Report

**Repo:** xk/library (`lb` media library CLI)
**Date:** 2026-08-13
**Scope:** `library/` source (~38k lines), cross-checked against `tests/`
**Method:** static analysis (ripgrep + targeted reads); every finding below was spot-verified against source.

---

## 1. Incomplete Features

Features that are stubbed, advertise modes they cannot deliver, or silently drop data.

### 1.1 Crash-on-use stubs (advertised mode raises `NotImplementedError`)

| Location | What is broken |
|---|---|
| `library/playback/media_player.py:661` | Playing via `python_mpv_jsonipc` **without** `--auto-seek` hits `raise NotImplementedError` (intended code is left as a comment). Only the auto-seek path works. |
| `library/playback/media_player.py:140-143` | `--chromecast` only implements `watch`/`listen` actions; `read`/`view`/`media` raise. |
| `library/misc/export_text.py:19-21` | `--format` only supports `html`; any other value raises `NotImplementedError`. |
| `library/files/llm_map.py:41-48` | No default prompt mode: `lb llm-map` without `--prompt`/`--rename` raises. |
| `library/playback/surf.py:27-29` | `--database` mode raises (`Currently only stdin is supported`). Command is also deprecated (`surf.py:11-16`) yet kept registered. |
| `library/text/cluster_sort.py:369-382` | `parse_args` advertises `--audio`, `--video`, `--text` profiles, but only `--lines` and `--image` are implemented; the other three raise. |
| `library/utils/gui.py:133-141` | `_get_coord_offset_from_monitor()` unconditionally raises; abandoned multi-monitor placement (also never called). |
| `library/tablefiles/mcda.py:115,123,163,189-205` | Four `TODO`-flagged features (`--weights`, PCA variance warning, categorical conversion, `--pairwise`) plus a large commented-out COMET block. |
| `library/utils/sqlgroups.py:371-377` | `--safe` download mode implemented for audio/video/image only; text/filesystem profiles raise. |
| `library/mediadb/download.py:238-239` | `download()` has no text-profile handler; raises. |
| `library/mediafiles/process_media.py:408,420` | Unknown media types raise in both `--simulate` and real-processing branches. |
| `library/createdb/site_add.py:143,150,179-181` | Unknown HTML/XML element types raise (Stylesheet/Script fall through `pass` to `NotImplementedError`). |
| `library/folders/similar_folders.py:53-55` / `library/files/similar_files.py:34-36` | "Nothing to do" (no filter flags) raises `NotImplementedError` instead of a clean usage error. |

### 1.2 Silent incompleteness (data dropped or side-effects lost)

| Location | Issue |
|---|---|
| `library/mediafiles/process_ffmpeg.py:449-452` | Multi-segment split output (`.%03d`): only the first segment (`.000`) is renamed/returned to the DB; the rest are orphaned. Marked `TODO: support / return multiple paths`. |
| `library/createdb/getty_add.py:59-60` | `Update` activity-stream records silently `continue`d (marked `TODO: implement in-band Update mechanism`). |
| `library/utils/web.py:1124-1125` | `WebPath.unlink()` is `pass` — deleting a URL-path no-ops silently. |
| `library/utils/web.py:504` | Resume-download verification (`TODO: check if first few kilobytes match`) not implemented. |
| `library/playback/playback_control.py:343` | Killed/stale mpv detection not implemented (`TODO: figure out if catt or mpv is stale`). |
| `library/playback/playback_control.py:55` | `segment_duration = segment_start - segment_end` produces negative durations when reversed (only a `TODO: could probably be simplified`). |
| `library/mediadb/block.py:67` | `TODO: add support for playlists table block rules`. |

### 1.3 Dead / orphaned code (defined, never called anywhere)

Complete implementations never wired in — features started but not connected:

- `library/utils/arg_utils.py:39` `split_folder_glob`
- `library/utils/log_utils.py:17` `format_args`
- `library/utils/strings.py:28` `safe_json_load` (the `safe_json_loads` variant is used)
- `library/utils/path_utils.py:426` `split_uri`
- `library/utils/pd_utils.py:115` `count_category`
- `library/utils/processes.py:555` `fzf_select`
- `library/utils/db_utils.py:235` `has_similar_schema`
- `library/utils/shell_utils.py:258,304,314` `fd_rglob_gen`, `file_temp_copy`, `tempdir_unlink`
- `library/utils/filter_engine.py:466` `FilterEngine.sort_items` (class used, method never called)
- `library/utils/iterables.py:81,131,212,233,260` `get_list_with_most_items`, `list_dict_filter_keys`, `return_unique_set_items`, `multi_split`, `zipkw`
- `library/utils/objects.py:24,36,49,153,255,263` `last_item`, `gen_is_empty`, `gen_len`, `filter_namespace`, `flip_dict`, `dict_filter_similar_key`
- `library/utils/web.py:1130` `WebPath.remote_name`
- `library/utils/argparse_utils.py:278` `suppress_arggroups`
- `library/editdb/dedupe_media.py:398` `filter_split_files`
- `library/playback/media_printer.py:72` `moved_media`
- `library/utils/gui.py:134` `_get_coord_offset_from_monitor` (see 1.1)

Production-only-dead (referenced only from `tests/`): `objects.replace_key_in_dict`/`replace_keys_in_dict`/`rename_key` (three overlapping key-rename implementations), `path_utils.build_nested_dir_dict`/`trim_path_segments`, `processes.load_or_install_modules`, `shell_utils.rename_no_replace`, `strings.last_chars`/`remove_excessive_linebreaks`, `web.extract_nearby_text`.

### 1.4 Left-in debugging hooks

| Location | Issue |
|---|---|
| `library/playback/media_printer.py:140-141` | `breakpoint()` gated only on `--verbose` debug level + `*` in cols. |
| `library/createdb/site_add.py:255-257` | `breakpoint()` gated on `--verbose > 2`. |

(Other `breakpoint()` calls in `eda.py`, `markdown_tables.py`, `plot.py` are gated on the documented `--repl` flag and appear intentional.)

### 1.5 TODO backlog (notable, unfinished behavior)

`process_media.py:279,301` (nested archives, csv/json→parquet), `unardel.py:63` (nested archives), `process_text.py:233` (`.doc` support), `processes.py:438` (slow), `printing.py:41` (SIGWINCH), `computer_info.py:247` (double-counted IO), `allocate_torrents.py:248` (nvme dir), `web_add.py:140,325` (head_foot_stream, Last-Modified skip), `tube_backend.py:585` ("wtf is this doing"), `search_db.py:62` ("replace with media_printer?"), `incremental_diff.py:39,78`, `dedupe_media.py:392` (false-positive sample-hash), `site_add.py:49,200` (foreign keys, websockets).

---

## 2. Contradictory Features

Features that conflict with each other or with their own documentation.

### 2.1 High-confidence bugs (behavior contradicts the flag/help/interface)

| # | Conflict |
|---|---|
| C1 | **`gallery_backend.is_supported` registered as 1-arg SQLite UDF but takes 2 args.** `gallery_backend.py:53` `def is_supported(args, url)`; `sqlgroups.py:374,426` registers it directly and calls it as `is_supported(m.path)`. `lb download --safe --image` crashes with `TypeError: missing 1 required positional argument: 'url'`. Contrast `tube_backend.py:109` (1 arg, works). |
| C2 | **Bare `-m`/`--multiple-playback` never enables multiple playback.** `arggroups.py:1062` sets `const=consts.DEFAULT_MULTIPLE_PLAYBACK` (`-1`, `consts.py:63`); `media_player.py:712` gates on `args.multiple_playback > 1`. `-1 > 1` is False, so bare `-m` silently falls back to single-player, contradicting the help text ("one per display; or two if only one display detected"). |
| C3 | **`--subtitle-mix` help text is inverted.** Help says "Probability to play no-subtitle content" (`play_actions.py:143`), but `arggroups.py:626` treats `random < subtitle_mix` as *prefer subtitles* — raising the value makes subtitled content more likely. Code comment (`bias slightly toward videos without subtitles`) matches behavior; the help text does not. |
| C4 | **`--delete-larger` aliased to `--delete-original` with contradictory semantics.** `arggroups.py:1580-1585` aliases the two; `process_ffmpeg.py:454-504` shows it deletes whichever is *larger* (keeps the smaller). The `--delete-original` alias implies unconditional original deletion. |
| C5 | **`history` usage documents `--frequency` the command doesn't accept.** `usage.py:395` shows `library history [--frequency daily weekly ...]`; `history.py:9-30` never adds that arggroup, so the documented flag errors with "unrecognized arguments". |
| C6 | **Download "profile required" error is dead code.** `download.py:70-72` errors when no profile given, but `arggroups.py:1725` sets a default profile of `video`, making the branch unreachable — `lb download dl.db` silently downloads as video instead of erroring as the message implies. |
| C7 | **`--mpv-socket` mismatch.** `watch` sessions use the watch socket (`play_actions.py:240-244`); all control subcommands (`now`/`next`/`seek`/`stop`/`pause`) default to the *listen* socket only (`playback_control.py:30`). You cannot control a running `watch` session with `lb next`/`lb stop`, despite `usage.py:11` saying you can. |
| C8 | **`stats` unsets `hide_deleted` after the SQL filter was already built.** `stats.py:33` runs `sql_fs_post` (appends `time_deleted=0` filter) then `stats.py:43-44` sets `hide_deleted = False`; any consumer of `args.filter_sql` still excludes deleted rows — intent contradicted by ordering. |
| C9 | **`getty_add` writes `media` with `pk="id"`** (`getty_add.py:209,211`) while every other module uses `pk=["playlists_id", "path"]` (`db_media.py:236,327`, `fs_add.py:114`, etc.) and never calls `db_media.create()`/`db_playlists.create()`. Creates a schema that conflicts with the unique index from `db_media.create`. |

### 2.2 Value / constant contradictions

| # | Conflict |
|---|---|
| C10 | **`wav`/`riff`/`rif` in both `AUDIO_ONLY_EXTENSIONS` and `IMAGE_EXTENSIONS`.** `consts.py:216` lists `wav` as audio; `consts.py:226` also lists `wav`, `riff`, `rif` as images. `lb fs-add --image` scans `.wav` as images while `--audio` scans them as audio; classification in `process_media.py:154,201` is ambiguous. |
| C11 | **Quarterly = 89 days vs 91 days.** `tabs_add.py:32` `get_days()` maps `"quarterly": 89`; `tabs_open.py:35` `frequency_filter()` maps `"quarterly": 91`. Same concept, different values. |
| C12 | **Accepted tab frequencies can never be served.** `consts.py:255` advertises `minutely`, `hourly`, `daily`, …, `decadally`; `sqlgroups.py:204-210` CASE and `tabs_open.py:31-37` mapper only handle `daily`–`yearly`. Tabs stored with `minutely`/`hourly`/`decadally` get `time_valid = NULL` and are excluded by the `time_valid < today` predicate (`sqlgroups.py:216`) — they can never open. (`tabs_add.py:31-33` *does* know `decadally`, worsening the split.) |
| C13 | **`SC.dedupe_media = "dedupe"` never matches the real action name.** `consts.py:162`; actual action derived from caller is `"dedupe-media"` (`arggroups.py:79`). Constant is dead and disagrees with reality. |
| C14 | **README subcommand count stale.** `.github/README.md:102` says "103 subcommands"; the code produces **102** (`__main__.py` `progs`). README also lists `search-help`, `mount`, `path` rows that aren't real subcommands. |

### 2.3 CLI-doc vs. behavior (lower severity)

- **Three different `--prefix` meanings** with different defaults across arggroups: download (`arggroups.py:1691`, `os.getcwd()`), qBittorrent (`arggroups.py:2699`, `Path.cwd()`), playback/SSHFS (`arggroups.py:986`, `""`).
- **`--multiple-playback` default `False` vs help implying default-off auto behavior** — see C2.
- Version number is consistent everywhere (`3.1.001`); no version conflict found.

---

## 3. Redundant Features

Duplicate implementations of the same concept; the canonical version is noted in each row.

### 3.1 Near-identical duplicate functions

| Cluster | Locations | Canonical |
|---|---|---|
| `collect_media` (DB-query-or-filesystem-scan + filter + attach stats) | `mediafiles/process_media.py:103`, `mediafiles/unardel.py:43`, `folders/big_dirs.py:157` (byte-identical to `disk_usage.get_data`) | `fsdb/disk_usage.py:283` / `fsdb/filesystem.py:36` (FilterEngine) |
| `get_data` | `fsdb/filesystem.py:36` (FilterEngine) vs `fsdb/disk_usage.py:283` (inline) | one of the two |
| `check_shrink` | `mediafiles/process_media.py:145` vs `mediafiles/unardel.py:56` (subset); whole `main()` bodies of both files are copy-paste siblings | `process_media.py` |
| `filter_deleted` | `utils/file_utils.py:429` (returns surviving paths) vs `playback/media_printer.py:14` (splits into local/http/deleted) — different return contracts, same idea | `file_utils.py` |
| `mark_media_deleted` / `mark_media_undeleted` chunked `WHERE path in (...)` UPDATE | `db_media.py:251,272` (differ only in `time_deleted` value), plus inline copies in `fsdb/search_db.py:62-80`, `mediadb/playlists.py:29`, `mediadb/block.py:144-163`, `play_actions.py` | `db_media.py` (one param) |
| `consolidate` | `db_media.py:84` vs `db_playlists.py:44` | shared schema-mapping helper |
| `add_media` / `add_playlist` / `consolidate_media` | `createdb/links_add.py:160,172,183` vs `createdb/web_add.py:89,100,252` (near-identical dicts) | shared `db_media`/`db_playlists` helpers |
| `is_supported` / `get_playlist_metadata` | `createdb/gallery_backend.py:53,182` vs `createdb/tube_backend.py:109,124` (parallel backend interfaces) | shared interface |
| `map_and_name` | `text/cluster_sort.py:90` vs `folders/similar_folders.py:67` (re-implements cluster_sort's) | `cluster_sort.py` |
| `sort_dicts` prologue | `text/regex_sort.py:305` vs `text/cluster_sort.py:201` (identical `search_columns`/sentence prologue) | shared helper |
| `get_subset` | `fsdb/folder_stats.py:240` (SQL) vs `fsdb/disk_usage.py:107` (in-memory) | one delegates to the other |
| `get_table` | `folders/move_list.py:56` vs `folders/scatter.py:71` | shared |
| `print_torrents_by_tracker` | `playback/torrents_info.py:425` (objects) vs `multidb/allocate_torrents.py:154` (dicts) | `torrents_info.py` (generalized) |
| `print_info` boilerplate (~25 lines) | `tablefiles/mcda.py:139` vs `tablefiles/eda.py:47` | extract to shared `tablefiles` code |
| `mv_to_keep_folder` | `misc/dedupe_czkawka.py:233` (blind move) vs `playback/post_actions.py:17` (DB-aware) | `post_actions.py` |
| `play` (browser-open + history) | `playback/links_open.py:70` vs `playback/tabs_open.py:49` (near-identical) | one merged command |
| `process_path` shell (gen_output_path → clobber → mkdir → stat → write → size compare) | `process_ffmpeg.py:63`, `process_image.py:41`, `process_text.py:173`, `pdf_edit.py:59` | one shared helper |
| `printer` (name collision, overlapping role) | `mediadb/search.py:41`, `playback/media_printer.py:325`, `text/nouns.py:73` | — |
| Duration/timestamp formatters | `strings.py:377,485,509`, `nums.py:133`, `printing.py:226` (all render seconds as human strings) | one canonical helper |
| `percent` | `nums.py:6` (compute ratio) vs `strings.py:432` (format string) — same name, different semantics | rename one |
| `cmd` (+ `print_std` logger) | `utils/processes.py:139` (local) vs `utils/remote_processes.py:9` (SSH) | share arg/print boilerplate |

### 3.2 Files that largely duplicate each other

| Files | Overlap |
|---|---|
| `fsdb/filesystem.py`, `fsdb/disk_usage.py`, `folders/big_dirs.py` | Same entry (DB-or-scan) + folder aggregation. `big_dirs` imports helpers from `disk_usage` yet still re-copies `get_data`. |
| `mediafiles/process_media.py`, `mediafiles/unardel.py` | End-to-end pipeline copy (collect → check → summary → confirm → unarchive → move). |
| `createdb/links_add.py`, `createdb/web_add.py` | Same scrape-loop + add/consolidate helpers (3.1). |
| `text/extract_text.py`, `text/extract_links.py` | Identical fetch boilerplate (`extract_text.py:106-121` ≈ `extract_links.py:207-223`); belongs in `utils/web.py`. |
| `playback/links_open.py`, `playback/tabs_open.py` | Duplicated `play()` + `--max-same-domain` filtering. |
| `utils/web.py` (encode) vs `utils/path_utils.py` (decode) | `safe_quote`/`url_encode` vs `safe_unquote`/`url_decode` — mirror-image nested structure; one pair with a `decode=` flag suffices. |
| `folders/similar_folders.py`, `files/similar_files.py` | Parallel "find similar items by cluster + size/count" tools; `similar_files` re-implements `is_same_size_group`/`cluster_by_size`. |
| `playback/torrents_info.py` vs `multidb/allocate_torrents.py` | `print_torrents_by_tracker` duplication (3.1). |

### 3.3 Repeated patterns within files

- `utils/devices.py:117` `clobber` vs `:308` `clobber_new_file` — same keep/delete/rename prompt logic.
- `db_media.py:472,536,651` — the big `WITH m as (...) ... play_count` query shell re-typed three times (only WHERE differs).
- `disk_usage.py:156,176,196` — `get_subset_group_by_{extensions,mimetypes,size}` identical loop skeletons.
- `play_actions.py:433-444` vs `:456-465` — the same `if regex_sort / elif cluster_sort: sort_dicts(...)` block twice.
- `utils/web.py` — `selenium_get_page`/`selenium_extract_html`/`infinite_scroll`/`scroll_down` nested scroll/wait loops duplicated.
- `path_utils.clean_path` (`path_utils.py:46`) — runs the identical clean-then-ftfy pipeline twice per path part (lines 63-68 and 71-74).
- `objects.py` — three key-rename implementations (`rename_key`, `replace_key_in_dict`, `replace_keys_in_dict`).

### 3.4 Overlapping CLI commands

- `search`/`s`/`sc` (`__main__.py:227`) vs `search_db` (`__main__.py:217`) — both SQL-search a media DB; `search_db` already targets the `media` table.
- `tabs_open` / `links_open` / `surf` (`__main__.py:245,256,257`) — three "open browser tabs" commands sharing `play()` logic.
- `torrents_info` / `torrents_dump` / `torrents_start` / `torrents_remaining` (`__main__.py:237-239,258-259`) — four torrent commands; `torrents_info` vs `torrents_remaining` both print per-tracker tables via the duplicated 3.1 helper.
- `media` (`db`,`open`) vs `watch`/`listen`/`read`/`view` (`__main__.py:246-250`) — the four wrappers only differ by `args.profiles`.
- `playlists` aliased as `folders` (`__main__.py:225`) — collides conceptually with the `library/folders/` command family.

### 3.5 Unused imports (ruff F401)

- `library/createdb/hn_add.py:106` — `import aiohttp` unused (availability check only).
- `library/utils/arggroups.py:2427` — `import numpy as np` unused.
- `library/utils/db_utils.py:5` — `from typing import TYPE_CHECKING` unused.

---

## 4. Confusing Logic & Bug Scan (agent-assisted review, 2026-08-13)

> Second scan pass targeting inverted/confusing logic and outright bugs. Items already
> documented above are cross-referenced rather than duplicated (e.g. negative duration
> `playback_control.py:62` is §1.2; the `media_printer.py:140` breakpoint is §1.4).

### 4.1 Definite bugs (verified against source)

| Location | Issue |
|---|---|
| `folders/merge_mv.py:220` | `parts = rel_p.parent.parts[args.modify_depth]` is a single path-component string; `os.path.join(*parts, name)` unpacks it into **characters** (`dir/file.mp4` → `d/i/r/file.mp4`). Needs a slice `parts[args.modify_depth:]`. |
| `mediadb/block.py:230` | `p = [p]` (single-element list) then `p[1] = data[args.match_column]` → `IndexError` on the normal "block a new URL" path whenever tube metadata contains the match column. |
| `createdb/fs_add.py:80-86` | `... or is_scan_all_files` puts the *entire* media list into **both** `image_media` and `other_media`; raw copies are appended last and `replace=True` on the same pk overwrites the exif-enriched rows → image metadata lost + every file processed twice. |
| `text/nouns.py:165` | `txt = strip_tags(txt)` where `txt` is undefined (loop var is `line`) → `UnboundLocalError` on `--html-strip`. |
| `createdb/tube_backend.py:319` | `entry["id"] = media_id` overwrites the real yt-dlp extractor id with the internal DB row id for every video fetched by `get_extra_metadata` → breaks `extractor_id` matching in `merge_online_local` and block rules. |
| `utils/filter_engine.py:433,440` | Filters receive an **age** (`consts.APPLICATION_START - d["time_created"]`) but the filters built in `arggroups.files_post`/`filter_src` expect an **epoch timestamp** → inverts `--created-within/--created-before/--time-*` (and modified variants) for `big_dirs`, `similar_files`, `disk_usage`, and filesystem mode. |
| `utils/path_utils.py:322` | `unquote(component, errors="strict")` — `errors` is the positional `encoding` param, so `LookupError` is raised for any `%XX` escape and swallowed → `safe_unquote` is a silent no-op. (Same wrong-kwarg pattern in `web.safe_quote`, harmless there.) |
| `utils/processes.py:263` | `process.communicate(input)` passes the builtin `input` function (no local shadows it) → `TypeError` if the process has `stdin=PIPE`, otherwise silently ignored. |
| `utils/web.py:1093` | `WebPath.head()` reads `self._head` before it is ever initialized (only set at line 1101) → `AttributeError` in the timeout thread surfaces as a confusing `TimeoutError` on first `stat()/exists()`. |
| `utils/web.py:1085` | `parts += "/".split(res.path)` and `"&".split(res.query)` split the *literal* `"/"`/`"&"` → always `["/"]`/`["&"]`; operands reversed. |
| `mediafiles/process_image.py:107` | `path.exists` without `()` → bound method is always truthy, so the fallback never returns `None`. |
| `mediafiles/media_check.py:226`, `createdb/av.py:216` | `args.delete_corrupt + "s"` where `delete_corrupt` is a float → `TypeError` exactly when about to delete a corrupt file (e.g. `--delete-corrupt 10`). |
| `mediafiles/process_ffmpeg.py:140-145` | AV1 early-return fires **before** the audio check, so `--audio-only` on an AV1 video returns the file unchanged (audio never transcoded); the opus `elif` is unreachable for that case. |
| `playback/media_printer.py:79-81` | `shlex.quote` (shell quoting) embedded into SQL → invalid SQL + injection vector for any path containing `'`. |
| `files/sample_compare.py:51-97` | Missing files are silently `suppress`ed from stats/hashes, so a nonexistent path can make `sample_cmp` return `True` (exit 0) — dangerous in dedupe workflows. |
| `createdb/fs_add.py:108,122` | Writes key `captions_t0` but checks/inserts `caption_t0` → file-tag caption is never written to the `captions` table. |
| `createdb/reddit_add.py:143-156` | `d["url"]` is reassigned to `url_overridden_by_dest` but the returned `path` uses the unchanged local `url` → skip-domain override is dead code. |
| `mediafiles/unardel.py:150-155` | `--move` requires `m["new_path"]` which is never set anywhere in the file (nothing is ever moved); `--move-broken` requires `not time_deleted` — the *opposite* of `process_media.py:466`, so healthy files get moved and broken ones don't. |
| `files/llm_map.py:95` | `args.llama_args` mutated inside the per-file loop → `--image` flags accumulate; every call after the first passes all prior files' images to the LLM. |

### 4.2 Suspicious (medium confidence)

| Location | Issue |
|---|---|
| `utils/sqlgroups.py:388-396` | `--same-domain` subquery is `FROM media` (unaliased) but filters on `m.*` → resolves to the *outer* row; the guard is always true. |
| `mediafiles/process_ffmpeg.py:336` | Split outputs (`.%03d`) rebuilt from the source `path`, discarding the target dir computed by `gen_output_path`/`clobber` → segments land in the source directory. |
| `editdb/dedupe_db.py:35-46` | `NOT IN (MIN(a), MIN(b), ...)` — the mins can come from *different* rows; the tuple may not exist → whole business-key groups deleted. (NULL semantics also silently keep rows.) |
| `playback/surf.py:59-71` | `readline()` has no EOF check; once stdin is exhausted it loops forever opening empty tabs if the browser doesn't create tabs for empty URLs. |
| `playback/media_printer.py:325-330` | Unbounded recursion retry on `FileNotFoundError` → `RecursionError` if rows keep resolving to deleted files. |
| `utils/arggroups.py:2884` | `args.dl_speed * 8` repeats the *list* ×8, not 8× each value (works only because `all(same)` over a repeated list is equivalent). |
| `utils/arg_utils.py:16-26` | `.replace("random", "random()")` substring-replaces column names → `--sort randomness` becomes `random()ness` (invalid SQL). |
| `utils/iterables.py:228` | `peek_value_exists` raises `StopIteration` on legitimately empty input instead of "no media found". |
| `text/cluster_sort.py:231` | `reverse=" desc" in args.sort` checks the play-order arg, not `sort_groups_by` → `--sort-groups-by '... desc'` never sorts descending. |
| `text/cluster_sort.py:314-329` | `cluster_images` builds `clusters` from per-image NN lists but indexes by path index → groupings become sequential blocks of ~k; nearest-neighbor data unused. |
| `text/cluster_sort.py:183,383` | `cluster_paths` returns raw strings for < 3 lines; the group sort key then does `d["grouped_paths"]` on a string → `TypeError`. |
| `text/extract_text.py:115-122` | 404 error-page HTML is still parsed/yielded; `is_error` is checked only after the yields. |
| `folders/big_dirs.py:225` | `--limit` limits *files* (applied before aggregation), not the number of displayed folders. |
| `folders/big_dirs.py:45-75,126` | `--parents` never shows the shallowest file's own folder (`min_parts` off-by-one); `--depth` without `--parents` hits `KeyError` on `d[parent]["folders"]` (key never created). |
| `folders/scatter.py:219-221` | `"free": used / total_used` — the `free` weight equals `used`, so `--policy free` behaves identically to `used`. |
| `playback/media_player.py:655-662` | `raise NotImplementedError` branch is dead (play() only reaches `mpv_jsonipc` when `--auto-seek` is set). |
| `playback/media_player.py:52` | `randrange(start, end - interdimensional_cable + 1)` → `ValueError: empty range` when the clip is shorter than the cable duration. |
| `playback/torrents_remaining.py:75-96` | `historical_eta` computed from *complete* torrents' `downloading_time` (≈0) → always ~0. |
| `playback/torrents_info.py:229` | `median([])` → `StatisticsError` on zero-file torrents with `--avg-sizes`. |
| `utils/devices.py:286-287,415-416` | `FolderOverFile.MERGE`: `while os.path.exists(parent_file)` descends into the just-renamed-away path → loop body only runs in `--simulate`. |
| `mediadb/download_status.py:53` | `m["time_downloaded"] + retry_delay` can be `None + int` → `TypeError`. |
| `tablefiles/eda.py:62`, `mcda.py:152` | `args.end_row not in df.shape` checks membership in the `(rows, cols)` tuple rather than comparing to the row count. |
| `utils/strings.py:548-565` | "in N days" off-by-one for future times with a remainder (timedelta floors toward −∞). |

### 4.3 Minor / cosmetic logic issues

| Location | Issue |
|---|---|
| `utils/strings.py:142-147` | Comment says "percent remaining" but returns fraction *watched*; `-P p` sorts opposite to `-P t`. |
| `utils/consts.py:198` | `reddit_frequency` maps both `quarterly` and `yearly` to `"year"`. |
| `utils/devices.py:100-103` | `log_size_diff` swaps source/destination sizes in its message. |
| `createdb/site_add.py:130` | `list.expand(...)` — Python lists have no `.expand` (dead/inverted branch). |
| `createdb/computers_add.py:44` | `raise RuntimeError` after `return` (dead code). |
| `utils/gui.py:128-129` | `int((s_width/2) - (s_width/2))` is always 0 (dead). |
| `playback/media_printer.py:173` | `("Aggregate" not in media[0].get("path") or "")` — trailing `or ""` is misleading. |
| `createdb/tabs_add.py:94-95` | Comment says "at least two days away" but code schedules the playhead *in the past*. |
| `mediafiles/torrents_dump.py:60-61` | Duplicate `"time_created"` dict key (first is dead). |
| `utils/filter_engine.py:601` | `raise ValueError("Unreachable?")` is genuinely unreachable (all wildcard combos handled above). |

### 4.4 Fix first (from this pass)

1. `merge_mv --modify-depth` path mangling (`merge_mv.py:220`).
2. `block.py:230` IndexError on blocking a new URL.
3. `fs_add` duplicate-media / lost-image-metadata scan (`fs_add.py:80-86`).
4. `nouns --html-strip` UnboundLocalError (`nouns.py:165`).
5. Inverted time filters (`filter_engine.py:433,440`).

---

## Priority Recommendations

**Contradictions worth fixing first** (silent user-facing misbehavior):
1. C2 — bare `-m` does nothing (dead documented feature).
2. C1 — `download --safe --image` crashes (TypeError).
3. C7 — `watch` sessions uncontrollable via `lb next`/`stop`/`seek`.
4. C3 — inverted `--subtitle-mix` semantics/help.
5. C12 — tabs with `minutely`/`hourly`/`decadally` frequencies can never open.

**Incomplete features worth finishing or removing:**
- `process_ffmpeg.py:449-452` multi-segment output (data currently orphaned).
- `media_player.py:661` non-auto-seek jsonipc playback stub.
- `cluster_sort.py:369-382` advertised-but-crashing profiles.
- 20+ orphaned utility functions (dead code; delete or wire in).
- Left-in `breakpoint()` calls in `media_printer.py` and `site_add.py`.

**Redundancy quick wins:**
- Delete `unardel.py` in favor of a `process_media` flag.
- Deduplicate `collect_media`/`get_data` across `big_dirs.py`/`disk_usage.py`/`filesystem.py`.
- Unify `links_open.play`/`tabs_open.play`.
- Extract `mcda`/`eda` `print_info` boilerplate.
- Generalize `torrents_info.print_torrents_by_tracker` and drop the `allocate_torrents` copy.
- Reconcile `wav`/`riff`/`rif` in `consts.py` (audio vs image).
