import json, random, time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

import library.utils.file_utils
from library import usage
from library.mediadb import db_media, db_playlists
from library.text import extract_links
from library.utils import arg_utils, arggroups, argparse_utils, consts, db_utils, objects, printing, strings, web
from library.utils.log_utils import log


def parse_args(action, **kwargs):
    parser = argparse_utils.ArgumentParser(**kwargs)
    parser.add_argument("--category", "-c")

    paging_parser = parser.add_argument_group("Paging")
    paging_parser.add_argument("--max-pages", type=int, help="Set a max number of pages to get")
    paging_parser.add_argument(
        "--fixed-pages",
        type=int,
        help="""Force a specific number of pages

Overrides --max-pages and --stop-known but you can still stop early via --stop-link ie. 429 page

If `--fixed-pages` is 1 and --start-page is not set then the URL will not be modified.

library links-add --fixed-pages=1
Loading page https://site/path

library links-add --fixed-pages=1 --page-start 99
Loading page https://site/path?page=99""",
    )
    paging_parser.add_argument(
        "--backfill-pages",
        "--backfill",
        type=int,
        help="""Similar to --fixed-pages but only for the first run

- Set `--backfill-pages` to the desired number of pages for the first run
- Set `--fixed-pages` to _always_ fetch the desired number of pages (remembered when using linksupdate)

If the website is supported by --auto-pager data is fetched twice when using page iteration.
As such, manual page iteration (--max-pages, --fixed-pages, etc) is disabled when using `--auto-pager`.

You can unset --fixed-pages for all the playlists in your database by running this command:
sqlite your.db "UPDATE playlists SET extractor_config = json_replace(extractor_config, '$.fixed_pages', null)"
""",
    )
    paging_parser.add_argument(
        "--page-step",
        "--step",
        type=int,
        default=1,
        help="""Use -1 for reverse paging

Some pages don't count page numbers but instead count items like messages or forum posts. You can iterate through like this:

library links-add --page-key start --page-start 0 --page-step 50

which translates to
&start=0    first page
&start=50   second page
&start=100  third page""",
    )
    paging_parser.add_argument("--page-start", "--start-page", "--start", type=int, help="Page number to start from")

    paging_parser.add_argument(
        "--page-key",
        default="page",
        help="""By default the script will attempt to modify each given URL with a specific query parameter, "&page=1".
Override like so:
library links-add --page-key p  # "&p=1"

Some websites use paths instead of query parameters. In this case the URL provided must include the matching page folder:
library links-add --page-key page https://website/page/1/
library links-add --page-key article https://website/article/1/
""",
    )
    paging_parser.add_argument(
        "--page-replace",
        help="""If you have more complicated needs you can replace the page number with a named variable:
library links-add --page-replace NUMBER https://site/with/complex-NUMBER
library links-add --page-replace NUMBER https://website/page/2?page=NUMBER
library links-add --page-replace NUMBER https://website/page/NUMBER?page=2
""",
    )

    paging_parser.add_argument(
        "--stop-pages-no-match",
        "--stop-no-match",
        type=int,
        default=4,
        help="""Some websites don't give an error when you try to access pages which don't exist.
To compensate for this the script will only continue fetching pages until there are neither new nor known links for four pages.""",
    )
    paging_parser.add_argument(
        "--stop-pages-no-new",
        "--stop-no-new",
        type=int,
        default=10,
        help="""After encountering ten pages with no new links we stop""",
    )
    paging_parser.add_argument(
        "--stop-new", type=int, help="Stop fetching pages when encountering fewer than or equal to N new links"
    )
    paging_parser.add_argument(
        "--stop-known", type=int, help="Stop fetching pages when encountering more than N known links"
    )
    paging_parser.add_argument("--stop-link", help="Stop fetching pages when hitting a specific link")

    arggroups.filter_links(parser)

    arggroups.requests(parser)
    arggroups.selenium(parser)
    arggroups.extractor(parser)
    parser.add_argument("--fetch-title", "--title", action="store_true")

    parser.add_argument("--force", action="store_true")

    arggroups.debug(parser)

    arggroups.database(parser)
    if "add" in action:
        arggroups.paths_or_stdin(parser)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser, create_db=True)

    if args.auto_pager or args.local_html:
        args.fixed_pages = 1

    arggroups.extractor_post(args)
    arggroups.filter_links_post(args)
    web.requests_session(args)  # prepare requests session
    arggroups.selenium_post(args)

    return args


def add_playlist(args, path):
    info = {
        "hostname": urlparse(path).hostname,
        "category": getattr(args, "category", None) or "Uncategorized",
        "time_created": consts.APPLICATION_START,
        "extractor_config": args.extractor_config,
        "time_modified": 0,
        "time_deleted": 0,
    }
    return db_playlists.add(args, str(path), info, extractor_key="LinksDB")


def consolidate_media(args, path: str) -> dict:
    return {
        "playlists_id": getattr(args, "playlists_id", None),
        "path": path,
        "category": getattr(args, "category", None) or "Uncategorized",
        "time_created": consts.APPLICATION_START,
        "time_modified": 0,
        "time_deleted": 0,
    }


def add_media(args, variadic):
    for path_or_dict in variadic:
        if isinstance(path_or_dict, str):
            path = strings.strip_enclosing_quotes(path_or_dict)
            d = objects.dict_filter_bool(consolidate_media(args, path))
        else:
            d = consolidate_media(args, strings.strip_enclosing_quotes(path_or_dict.pop("path")))
            d = objects.dict_filter_bool({**d, **path_or_dict})

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
    if args.page_start is None:
        page_start = 1 if args.page_step == 1 else 0
    else:
        page_start = args.page_start

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

        if (page_limit == 1 and args.page_start is None) or (page_value == (args.page_start or 0) == 0):
            page_path = playlist_path
        elif args.page_replace:
            page_path = playlist_path.replace(args.page_replace, str(page_value))
        else:
            page_path = set_page(playlist_path, args.page_key, page_value)

        log.info("Loading page %s", page_path)
        page_known = set()
        page_new = {}
        try:
            for link_dict in extract_links.get_inner_urls(args, page_path):
                link = link_dict.pop("link")

                if link == args.stop_link:
                    end_of_playlist = True
                    break

                if link in page_known:
                    pass
                elif db_media.exists(args, link):
                    page_known.add(link)
                    if args.category:
                        update_category(args, link)
                else:
                    page_new[link] = objects.merge_dict_values_str(page_new.get(link) or {}, link_dict)

                printing.print_overwrite(f"Page {page_count} link scan: {len(page_new)} new [{len(page_known)} known]")
            print()

            if not (args.backfill_pages or args.fixed_pages):
                if (args.stop_known and len(page_known) > args.stop_known) or (
                    args.stop_new and args.stop_new >= len(page_new)
                ):
                    end_of_playlist = True
                    break
        except requests.HTTPError as e:
            log.error(e)

        add_media(args, [{"path": k, **v} for k, v in page_new.items()])

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
    args = parse_args(consts.SC.links_add, usage=usage.links_add)

    db_playlists.create(args)
    db_media.create(args)

    if args.fetch_title:
        if args.selenium:
            web.load_selenium(args)
        try:
            media_new = set()
            media_known = set()
            for url in library.utils.file_utils.gen_paths(args):
                if url in media_known:
                    continue

                d = db_media.get(args, url)
                if d:
                    media_known.add(url)
                else:
                    media_new.add(url)
                    d = consolidate_media(args, url)

                d["title"] = web.get_title(args, url)

                add_media(args, [d])
                printing.print_overwrite(f"Link import: {len(media_new)} new [{len(media_known)} known]")
            print()
        finally:
            if args.selenium:
                web.quit_selenium(args)
    elif args.no_extract:
        media_new = set()
        media_known = set()
        for p in library.utils.file_utils.gen_paths(args):
            if db_media.exists(args, p):
                media_known.add(p)
                if args.category:
                    update_category(args, p)
            else:
                add_media(args, [p])
                media_new.add(p)
            printing.print_overwrite(f"Link import: {len(media_new)} new [{len(media_known)} known]")
        print()
    else:
        if args.selenium:
            web.load_selenium(args)
        try:
            playlist_count = 0
            for playlist_path in library.utils.file_utils.gen_paths(args):
                args.playlists_id = add_playlist(args, playlist_path)
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
    args = parse_args(consts.SC.links_update, usage=usage.links_update)

    link_playlists = db_playlists.get_all(
        args,
        order_by="""length(path)-length(REPLACE(path, '/', '')) desc
        , random()
        """,
    )

    selenium_needed = args.selenium or any(
        json.loads(d.get("extractor_config") or "{}").get("selenium") for d in link_playlists
    )
    if selenium_needed:
        web.load_selenium(args)

    try:
        playlist_count = 0
        for playlist in link_playlists:
            extractor_config = json.loads(playlist.get("extractor_config") or "{}")
            args_env = arg_utils.override_config(args, extractor_config)

            new_media = extractor(args_env, playlist["path"])

            if new_media > 0:
                db_playlists.update_more_frequently(args, playlist["path"])
            else:
                db_playlists.update_less_frequently(args, playlist["path"])

            if playlist_count > 3:
                time.sleep(random.uniform(0.05, 2))
            playlist_count += 1

    finally:
        if selenium_needed:
            web.quit_selenium(args)
