import argparse, json, random, time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from xklb import db_media, db_playlists, usage
from xklb.scripts.mining import extract_links
from xklb.utils import arg_utils, consts, db_utils, objects, printing, strings, web
from xklb.utils.log_utils import log


def parse_args(**kwargs):
    parser = argparse.ArgumentParser(**kwargs)
    parser.add_argument("--category", "-c", help=argparse.SUPPRESS)
    parser.add_argument("--no-extract", "--skip-extract", action="store_true")

    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--fixed-pages", type=int)
    parser.add_argument("--backfill-pages", "--backfill", type=int)

    parser.add_argument("--stop-pages-no-match", "--stop-no-match", type=int, default=4)
    parser.add_argument("--stop-pages-no-new", "--stop-no-new", type=int, default=10)
    parser.add_argument("--stop-new", type=int)
    parser.add_argument("--stop-known", type=int)
    parser.add_argument("--stop-link")

    parser.add_argument("--page-replace")
    parser.add_argument("--page-key", default="page")
    parser.add_argument("--page-step", "--step", "-S", type=int, default=1)
    parser.add_argument("--page-start", "--start-page", "--start", type=int)

    parser.add_argument(
        "--path-include",
        "--include-path",
        "--include",
        "-s",
        nargs="*",
        default=[],
        help="path substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--text-include",
        "--include-text",
        nargs="*",
        default=[],
        help="link text substrings for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--after-include",
        "--include-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--before-include",
        "--include-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for inclusion (all must match to include)",
    )
    parser.add_argument(
        "--path-exclude",
        "--exclude-path",
        "--exclude",
        "-E",
        nargs="*",
        default=["javascript:", "mailto:", "tel:"],
        help="path substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--text-exclude",
        "--exclude-text",
        nargs="*",
        default=[],
        help="link text substrings for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--after-exclude",
        "--exclude-after",
        nargs="*",
        default=[],
        help="plain text substrings after URL for exclusion (any must match to exclude)",
    )
    parser.add_argument(
        "--before-exclude",
        "--exclude-before",
        nargs="*",
        default=[],
        help="plain text substrings before URL for exclusion (any must match to exclude)",
    )

    parser.add_argument("--strict-include", action="store_true", help="All include args must resolve true")
    parser.add_argument("--strict-exclude", action="store_true", help="All exclude args must resolve true")
    parser.add_argument("--case-sensitive", action="store_true", help="Filter with case sensitivity")
    parser.add_argument(
        "--no-url-decode",
        "--skip-url-decode",
        action="store_true",
        help="Skip URL-decode for --path-include/--path-exclude",
    )

    parser.add_argument("--cookies", help="path to a Netscape formatted cookies file")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]")

    parser.add_argument("--selenium", action="store_true")
    parser.add_argument("--manual", action="store_true", help="Confirm manually in shell before exiting the browser")
    parser.add_argument("--scroll", action="store_true", help="Scroll down the page; infinite scroll")
    parser.add_argument("--auto-pager", "--autopager", action="store_true")
    parser.add_argument("--poke", action="store_true")
    parser.add_argument("--chrome", action="store_true")
    parser.add_argument("--force", action="store_true")

    parser.add_argument("--db", "-db", help=argparse.SUPPRESS)
    parser.add_argument("--verbose", "-v", action="count", default=0)

    parser.add_argument("--local-file", "--local-html", action="store_true", help="Treat paths as Local HTML files")
    parser.add_argument("--file", "-f", help="File with one URL per line")

    parser.add_argument("database", help=argparse.SUPPRESS)
    if "add" in kwargs["prog"]:
        parser.add_argument("paths", nargs="*", action=arg_utils.ArgparseArgsOrStdin, help=argparse.SUPPRESS)
    args = parser.parse_intermixed_args()

    if args.auto_pager:
        args.fixed_pages = 1

    if args.scroll:
        args.selenium = True

    if not args.case_sensitive:
        args.before_include = [s.lower() for s in args.before_include]
        args.path_include = [s.lower() for s in args.path_include]
        args.text_include = [s.lower() for s in args.text_include]
        args.after_include = [s.lower() for s in args.after_include]
        args.before_exclude = [s.lower() for s in args.before_exclude]
        args.path_exclude = [s.lower() for s in args.path_exclude]
        args.text_exclude = [s.lower() for s in args.text_exclude]
        args.after_exclude = [s.lower() for s in args.after_exclude]

    if not args.no_url_decode:
        args.path_include = [web.url_decode(s) for s in args.path_include]
        args.path_exclude = [web.url_decode(s) for s in args.path_exclude]

    if args.db:
        args.database = args.db
    Path(args.database).touch()
    args.db = db_utils.connect(args)

    log.info(objects.dict_filter_bool(args.__dict__))
    return args, parser


def add_playlist(args, path):
    info = {
        "hostname": urlparse(path).hostname,
        "category": getattr(args, "category", None) or "Uncategorized",
        "time_created": consts.APPLICATION_START,
        "extractor_config": {
            k: v for k, v in args.__dict__.items() if k not in ["db", "database", "verbose", "paths", "backfill_pages"]
        },
        "time_deleted": 0,
    }
    args.playlists_id = db_playlists.add(args, str(path), info)


def consolidate_media(args, path: str) -> dict:
    return {
        "path": path,
        "category": getattr(args, "category", None) or "Uncategorized",
        "time_created": consts.APPLICATION_START,
        "time_deleted": 0,
    }


def add_media(args, variadic):
    for path_or_dict in variadic:
        if isinstance(path_or_dict, str):
            path = strings.strip_enclosing_quotes(path_or_dict)
            d = objects.dict_filter_bool(consolidate_media(args, path))
        else:
            d = objects.dict_filter_bool(
                {
                    **consolidate_media(args, strings.strip_enclosing_quotes(path_or_dict["path"])),
                    "title": strings.strip_enclosing_quotes(path_or_dict["title"]),
                }
            )
        db_media.add(args, d)


def set_page(input_string, page_key, page_number):
    parsed_url = urlparse(input_string)

    path_parts = parsed_url.path.split("/")

    if page_key in path_parts:
        page_key_index = path_parts.index(page_key)
        path_parts[page_key_index + 1] = str(page_number)  # Replace the page number at the next index
        updated_path = "/".join(path_parts)
        modified_url = urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                updated_path,
                parsed_url.params,
                parsed_url.query,
                parsed_url.fragment,
            )
        )
    else:
        query_params = parse_qs(parsed_url.query)
        query_params[page_key] = [str(page_number)]
        updated_query = urlencode(query_params, doseq=True)
        modified_url = urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                updated_query,
                parsed_url.fragment,
            )
        )

    return modified_url


def count_pages(args, page_limit):
    page_start = 1 if args.page_start is None else args.page_start
    if page_limit:
        yield from range(page_start, page_start + (page_limit * args.page_step), args.page_step)
    else:
        page_num = page_start
        while True:
            yield page_num
            page_num += args.page_step


def update_category(args, path):
    with args.db.conn:
        args.db.conn.execute("UPDATE media SET category = ? WHERE path = ?", [args.category, path])


def extractor(args, playlist_path):
    known_media = set()
    new_media = set()
    end_of_playlist = False
    page_limit = args.backfill_pages or args.fixed_pages or args.max_pages

    page_count = 0
    page_count_since_match = 0
    page_count_since_new = 0
    for page_value in count_pages(args, page_limit):
        if end_of_playlist:
            break

        page_count += 1
        if page_count > 3:
            time.sleep(random.uniform(0.3, 4.55))

        if page_limit == 1 and args.page_start is None:
            page_path = playlist_path
        elif args.page_replace:
            page_path = playlist_path.replace(args.page_replace, str(page_value))
        else:
            page_path = set_page(playlist_path, args.page_key, page_value)

        log.info("Loading page %s", page_path)
        page_known = set()
        page_new = {}
        for a_ref in extract_links.get_inner_urls(args, page_path):
            if a_ref is None:
                end_of_playlist = True
                break

            link, link_text = a_ref

            if link == args.stop_link:
                end_of_playlist = True
                break

            if link in page_known:
                pass
            elif db_media.exists(args, link):
                page_known.add(link)
                if args.category:
                    update_category(args, link)
            elif link in page_new:
                page_new[link] = strings.combine(page_new[link], link_text)
            else:
                page_new[link] = link_text

            printing.print_overwrite(f"Page {page_count} link scan: {len(page_new)} new [{len(page_known)} known]")

            if not (args.backfill_pages or args.fixed_pages):
                if (args.stop_known and len(page_known) > args.stop_known) or (
                    args.stop_new and args.stop_new >= len(page_new)
                ):
                    end_of_playlist = True
                    break

        add_media(args, [{"path": k, "title": v} for k, v in page_new.items()])

        new_media |= set(page_new.keys())
        known_media |= page_known

        if len(page_new) > 0:
            page_count_since_new = 0
        else:
            page_count_since_new += 1
        if len(page_new) > 0 or len(page_known) > 0:
            page_count_since_match = 0
        else:
            page_count_since_match += 1

        if not (args.backfill_pages or args.fixed_pages) and (
            page_count_since_new >= args.stop_pages_no_new or page_count_since_match >= args.stop_pages_no_match
        ):
            end_of_playlist = True
    print()

    print(
        f"{len(new_media)} new [{len(known_media)} known] in {page_count} pages (avg {len(new_media) // page_count} new [{len(known_media) // page_count} known])"
    )
    return len(new_media)


def links_add() -> None:
    args, _parser = parse_args(prog="library links-add", usage=usage.links_add)

    if args.no_extract:
        media_new = set()
        media_known = set()
        for p in arg_utils.gen_paths(args):
            if db_media.exists(args, p):
                media_known.add(p)
                if args.category:
                    update_category(args, p)
            else:
                add_media(args, [p])
                media_new.add(p)
            printing.print_overwrite(f"Link import: {len(media_new)} new [{len(media_known)} known]")
    else:
        if args.selenium:
            web.load_selenium(args)
        try:
            playlist_count = 0
            for playlist_path in arg_utils.gen_paths(args):
                add_playlist(args, playlist_path)
                extractor(args, playlist_path)

                if playlist_count > 3:
                    time.sleep(random.uniform(0.05, 2))
                playlist_count += 1

        finally:
            if args.selenium:
                web.quit_selenium(args)

    if not args.db["media"].detect_fts():
        db_utils.optimize(args)


def links_update() -> None:
    args, parser = parse_args(prog="library links-update", usage=usage.links_update)

    link_playlists = db_playlists.get_all(
        args,
        order_by="""length(path)-length(REPLACE(path, '/', '')) desc
        , random()
        """,
    )

    selenium_needed = any([json.loads(d.get("extractor_config") or "{}").get("selenium") for d in link_playlists])
    if selenium_needed:
        web.load_selenium(args)

    try:
        playlist_count = 0
        for playlist in link_playlists:
            extractor_config = json.loads(playlist.get("extractor_config") or "{}")
            args_env = arg_utils.override_config(parser, extractor_config, args)

            new_media = extractor(args_env, playlist["path"])

            if new_media > 0:
                db_playlists.decrease_update_delay(args, playlist["path"])
            else:
                db_playlists.increase_update_delay(args, playlist["path"])

            if playlist_count > 3:
                time.sleep(random.uniform(0.05, 2))
            playlist_count += 1

    finally:
        if selenium_needed:
            web.quit_selenium(args)


if __name__ == "__main__":
    links_add()
