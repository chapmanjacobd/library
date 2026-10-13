import argparse, math

from library.mediadb import db_history
from library.playback import media_printer
from library.utils import arggroups, argparse_utils, consts, db_utils, devices, processes
from library.utils.log_utils import log
from library.utils.sqlgroups import construct_tabs_query

USAGE = {
    'tabs_open': """library tabs open DATABASE

    Tabs runs **once per day**. Configure it with `crontab`:

        45 9 * * * DISPLAY=:0 library tabs /home/my/tabs.db

    If things aren't working you can use `at` to simulate a similar environment as `cron`

        echo 'fish -c "export DISPLAY=:0 && library tabs /full/path/to/tabs.db"' | at NOW

    Also, if you're just testing things out be aware that `tabs-add` assumes that you visited the
    website right before adding it; eg. `tabs-add --frequency yearly` today opens the tab no sooner
    than one year later (at most). Override this default:

        library database add tabs --allow-immediate ...

    To re-"play" some tabs, delete some history

        library database history ~/lb/tabs.db --played-within '1 day' -L inf -p --delete-rows
        library tabs ~/lb/tabs.db

    You can also invoke tabs manually

        library tabs -L 1  # open one tab

    Print URLs

        library tabs -w "frequency='yearly'" -p

    View how many yearly tabs you have

        library tabs -w "frequency='yearly'" -p a

    Delete URLs

        library tabs -p -s cyber
        ╒═══════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                  │ frequency   │ time_valid   │
        ╞═══════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/cyberDeck/to │ yearly      │ Dec 31 1970  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/to │ yearly      │ Aug 29 2023  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://www.reddit.com/r/cyberDeck/   │ yearly      │ Sep 05 2023  │
        ╘═══════════════════════════════════════╧═════════════╧══════════════╛

        library tabs -p -w "path='https://www.reddit.com/r/cyberDeck/'" --delete-rows
        Removed 1 metadata records

        library tabs -p -s cyber
        ╒═══════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                  │ frequency   │ time_valid   │
        ╞═══════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/cyberDeck/to │ yearly      │ Dec 31 1970  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/to │ yearly      │ Aug 29 2023  │
        │ p/?sort=top&t=year                    │             │              │
        ╘═══════════════════════════════════════╧═════════════╧══════════════╛
""",
}


def parse_args() -> argparse.Namespace:
    parser = argparse_utils.ArgumentParser(usage=USAGE['tabs_open'])

    arggroups.sql_fs(parser)
    parser.add_argument("--max-same-domain", type=int, help="Limit to N tabs per domain")
    parser.add_argument("--browser", nargs="?", const="default")
    arggroups.debug(parser)

    arggroups.database(parser)
    parser.add_argument("search", nargs="*")

    parser.set_defaults(fts=False)
    args = parser.parse_intermixed_args()
    arggroups.args_post(args, parser)

    arggroups.sql_fs_post(args)
    return args


def frequency_filter(counts, media: list[dict]) -> list[dict]:
    mapper = {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
        "quarterly": 91,
        "yearly": 365,
    }
    filtered_media = []
    for freq, freq_count in counts:
        num_days = mapper.get(freq, 365)
        num_tabs = max(1, math.ceil(freq_count / num_days))
        log.debug(f"freq_count {freq_count} / num_days {num_days} = num_tabs {num_tabs}")

        filtered_media.extend([m for m in media if m["frequency"] == freq][:num_tabs])

    return filtered_media


def play(args, media):
    links = [m["path"] for m in media]
    devices.browse(args.browser or "default", links)
    db_history.add(args, links, time_played=consts.today_stamp(), mark_done=True)


def tabs_open() -> None:
    args = parse_args()
    if not args.simulate:
        db_history.create(args)

    from library.utils.path_utils import domain_from_url

    args.db.register_function(domain_from_url, deterministic=True)

    query, bindings = construct_tabs_query(args)

    if args.print or args.delete_rows or args.mark_deleted or args.mark_watched:
        media_printer.printer(args, query, bindings)
        return

    media = list(args.db.query(query, bindings))
    if not media:
        processes.no_media_found()

    m_columns = db_utils.columns(args, "media")
    counts = args.db.execute(
        f"""
        SELECT
            frequency, count(*)
        FROM media
        WHERE 1=1
            {"and COALESCE(time_deleted,0)=0" if 'time_deleted' in m_columns else ''}
        GROUP BY 1
    """
    ).fetchall()
    media = frequency_filter(counts, media)

    if args.simulate:
        media_printer.media_printer(args, media)
        return
    else:
        play(args, media)
