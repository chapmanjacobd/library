from xklb import lb, usage

progs = {
    "Create database subcommands": {
        "fsadd": "Add local media",
        "tubeadd": "Add online video media (yt-dlp)",
        "galleryadd": "Add online gallery media (gallery-dl)",
        "tabsadd": "Add browser tabs",
        "redditadd": "Add reddit media",
        "pushshift": "Convert pushshift data to reddit.db format",
        "hnadd": "Create / Update a Hacker News database",
        "substack": "Backup substack articles",
        "tildes": "Backup tildes comments and topics",
        "places_import": "Import places of interest (POIs)",
    },
    "Update database subcommands": {
        "fsupdate": "Update local media",
        "tubeupdate": "Update online video media",
        "galleryupdate": "Update online gallery media",
        "redditupdate": "Update reddit media",
    },
    "Media database subcommands": {
        "watch": "Watch / Listen",
        "tabs": "Open tabs",
        "block": "Block a channel",
        "playlists": "List playlists",
        "download": "Download media",
        "download_status": "Download Status",
        "redownload": "Re-download deleted/lost media",
        "history": "History",
        "search": "Search captions / subtitles",
    },
    "Text subcommands": {
        "cluster_sort": "Sort text and images by similarity",
        "extract_links": "Extract links from HTML pages",
    },
    "File subcommands": {
        "eda": "Exploratory Data Analysis",
        "incremental_diff": "Compare data files",
    },
    "Folder subcommands": {
        "relmv": "Move files preserving parent folder hierarchy",
        "scatter": "Scatter files between folders or disks",
        "mv_list": "Find specific folders to move to different disks",
    },
    "Multi-database subcommands": {
        "merge_dbs": "Merge SQLITE databases",
        "copy_play_counts": "Copy play history",
    },
    "Filesystem Database subcommands": {
        "christen": "Clean filenames",
        "disk_usage": "Disk Usage",
        "bigdirs": "Show large folders",
        "search_db": "Search a SQLITE database",
        "optimize": "Re-optimize database",
    },
    "Database enrichment subcommands": {
        "dedupe_db": "Dedupe SQLITE tables",
        "dedupe": "Dedupe similar media",
        "merge_online_local": "Merge online and local data",
        "mpv_watchlater": "Import mpv watchlater files to history",
        "reddit_selftext": "Convert selftext links to media table",
    },
    "Misc subcommands": {
        "surf": "Automatic tab loader",
        "export_text": "Export HTML files from SQLite databases",
    },
}

all_progs = [s for s in dir(usage) if not s.startswith("_") and isinstance(getattr(usage, s), str)]
categorized_progs = [key for d in progs.values() for key in d if isinstance(key, str)]
other_progs = [s for s in all_progs if s not in categorized_progs]
if len(other_progs) > 0:
    progs["Other subcommands"] = {s: s for s in other_progs}

usage_details = []
for category, category_progs in progs.items():
    usage_details.append(f"\n### {category}\n")

    for prog, prog_description in category_progs.items():
        prog_usage = getattr(usage, prog)
        subcommand = prog.replace("_", "-")

        if prog_description is None:
            prog_description = subcommand

        if subcommand not in prog_description.lower():
            prog_description += f" ({subcommand})"
        usage_details.append(
            f"""
<details><summary>{prog_description}</summary>

    $ library {subcommand} -h
    usage: {prog_usage}

</details>
""",
        )

expand_all_js = """```js
(() => { const readmeDiv = document.getElementById("readme"); const detailsElements = readmeDiv.getElementsByTagName("details"); for (let i = 0; i < detailsElements.length; i++) { detailsElements[i].setAttribute("open", "true"); } })();
```"""

readme = rf"""# library (media toolkit)

A wise philosopher once told me: "the future is [autotainment](https://www.youtube.com/watch?v=F9sZFrsjPp0)".

Manage and curate large media libraries. An index for your archive.
Primary usage is local filesystem but also supports some virtual constructs like
tracking online video playlists (eg. YouTube subscriptions) and scheduling browser tabs.

## Install

Linux recommended but [Windows setup instructions](./Windows.md) available.

    pip install xklb

Should also work on Mac OS.

### External dependencies

Required: `ffmpeg`

Some features work better with: `mpv`, `firefox`, `fish`

## Getting started

<details><summary>Local media</summary>

### 1. Extract Metadata

For thirty terabytes of video the initial scan takes about four hours to complete.
After that, subsequent scans of the path (or any subpaths) are much quicker--only
new files will be read by `ffprobe`.

    library fsadd tv.db ./video/folder/

![termtosvg](./examples/extract.svg)

### 2. Watch / Listen from local files

    library watch tv.db                           # the default post-action is to do nothing
    library watch tv.db --post-action delete      # delete file after playing
    library listen finalists.db -k ask_keep       # ask whether to keep file after playing

To stop playing press Ctrl+C in either the terminal or mpv

</details>

<details><summary>Online media</summary>

### 1. Download Metadata

Download playlist and channel metadata. Break free of the YouTube algo~

    library tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

[![termtosvg](./examples/tubeadd.svg "library tubeadd example")](https://asciinema.org/a/BzplqNj9sCERH3A80GVvwsTTT)

And you can always add more later--even from different websites.

    library tubeadd maker.db https://vimeo.com/terburg

To prevent mistakes the default configuration is to download metadata for only
the most recent 20,000 videos per playlist/channel.

    library tubeadd maker.db --extractor-config playlistend=1000

Be aware that there are some YouTube Channels which have many items--for example
the TEDx channel has about 180,000 videos. Some channels even have upwards of
two million videos. More than you could likely watch in one sitting--maybe even one lifetime.
On a high-speed connection (>500 Mbps), it can take up to five hours to download
the metadata for 180,000 videos.

TIP! If you often copy and paste many URLs you can paste line-delimited text as arguments via a subshell. For example, in `fish` shell with [cb](https://github.com/niedzielski/cb):

    library tubeadd my.db (cb)

Or in BASH:

    library tubeadd my.db $(xclip -selection c)

#### 1a. Get new videos for saved playlists

Tubeupdate will go through the list of added playlists and fetch metadata for
any videos not previously seen.

    library tubeupdate tube.db

### 2. Watch / Listen from websites

    library watch maker.db

To stop playing press Ctrl+C in either the terminal or mpv

</details>

<details><summary>List all subcommands</summary>

    $ library
    {lb.usage()}

</details>

## Examples

### Watch online media on your PC

    wget https://github.com/chapmanjacobd/library/raw/main/example_dbs/mealtime.tw.db
    library watch mealtime.tw.db --random --duration 30m

### Listen to online media on a chromecast group

    wget https://github.com/chapmanjacobd/library/raw/main/example_dbs/music.tl.db
    library listen music.tl.db -ct "House speakers" --random

### Hook into HackerNews

    wget https://github.com/chapmanjacobd/hn_mining/raw/main/hackernews_only_direct.tw.db
    library watch hackernews_only_direct.tw.db --random --ignore-errors

### Organize via separate databases

    library fsadd --audio both.db ./audiobooks/ ./podcasts/
    library fsadd --audio audiobooks.db ./audiobooks/
    library fsadd --audio podcasts.db ./podcasts/ ./another/more/secret/podcasts_folder/

## Guides

### Music alarm clock

<details><summary>via termux crontab</summary>

Wake up to your own music

    30 7 * * * library listen ./audio.db

Wake up to your own music _only when you are *not* home_ (computer on local IP)

    30 7 * * * timeout 0.4 nc -z 192.168.1.12 22 || library listen --random

Wake up to your own music on your Chromecast speaker group _only when you are home_

    30 7 * * * ssh 192.168.1.12 library listen --cast --cast-to "Bedroom pair"

</details>


### Browser Tabs

<details><summary>Visit websites on a schedule</summary>

`tabs` is a way to organize your visits to URLs that you want to remember every once in a while.

The main benefit of tabs is that you can have a large amount of tabs saved (say 500 monthly tabs) and only the smallest
amount of tabs to satisfy that goal (500/30) tabs will open each day. 17 tabs per day seems manageable--500 all at once does not.

The use-case of tabs are websites that you know are going to change: subreddits, games,
or tools that you want to use for a few minutes daily, weekly, monthly, quarterly, or yearly.

### 1. Add your websites

    library tabsadd tabs.db --frequency monthly --category fun \
        https://old.reddit.com/r/Showerthoughts/top/?sort=top&t=month \
        https://old.reddit.com/r/RedditDayOf/top/?sort=top&t=month

### 2. Add library tabs to cron

library tabs is meant to run **once per day**. Here is how you would configure it with `crontab`:

    45 9 * * * DISPLAY=:0 library tabs /home/my/tabs.db

Or with `systemd`:

    tee ~/.config/systemd/user/tabs.service
    [Unit]
    Description=xklb daily browser tabs

    [Service]
    Type=simple
    RemainAfterExit=no
    Environment="DISPLAY=:0"
    ExecStart="/usr/bin/fish" "-c" "lb tabs /home/xk/lb/tabs.db"

    tee ~/.config/systemd/user/tabs.timer
    [Unit]
    Description=xklb daily browser tabs timer

    [Timer]
    Persistent=yes
    OnCalendar=*-*-* 9:58

    [Install]
    WantedBy=timers.target

    systemctl --user daemon-reload
    systemctl --user enable --now tabs.service

You can also invoke tabs manually:

    library tabs tabs.db -L 1  # open one tab

Incremental surfing. 📈🏄 totally rad!

</details>

### Find large folders

<details><summary>Curate with library bigdirs</summary>

If you are looking for candidate folders for curation (ie. you need space but don't want to buy another hard drive).
The bigdirs subcommand was written for that purpose:

    $ library bigdirs fs/d.db

You may filter by folder depth (similar to QDirStat or WizTree)

    $ library bigdirs --depth=3 audio.db

There is also an flag to prioritize folders which have many files which have been deleted (for example you delete songs you don't like--now you can see who wrote those songs and delete all their other songs...)

    $ library bigdirs --sort-by deleted audio.db

Recently, this functionality has also been integrated into watch/listen subcommands so you could just do this:

    $ library watch --big-dirs ./my.db
    $ lb wt -B  # shorthand equivalent

</details>

### Backfill data

<details><summary>Backfill missing YouTube videos from the Internet Archive</summary>

```fish
for base in https://youtu.be/ http://youtu.be/ http://youtube.com/watch?v= https://youtube.com/watch?v= https://m.youtube.com/watch?v= http://www.youtube.com/watch?v= https://www.youtube.com/watch?v=
    sqlite3 video.db "
        update or ignore media
            set path = replace(path, '$base', 'https://web.archive.org/web/2oe_/http://wayback-fakeurl.archive.org/yt/')
              , time_deleted = 0
        where time_deleted > 0
        and (path = webpath or path not in (select webpath from media))
        and path like '$base%'
    "
end
```

</details>

<details><summary>Backfill reddit databases with pushshift data</summary>

[https://github.com/chapmanjacobd/reddit_mining/](https://github.com/chapmanjacobd/reddit_mining/)

```fish
for reddit_db in ~/lb/reddit/*.db
    set subreddits (sqlite-utils $reddit_db 'select path from playlists' --tsv --no-headers | grep old.reddit.com | sed 's|https://old.reddit.com/r/\(.*\)/|\1|' | sed 's|https://old.reddit.com/user/\(.*\)/|u_\1|' | tr -d "\r")

    ~/github/xk/reddit_mining/links/
    for subreddit in $subreddits
        if not test -e "$subreddit.csv"
            echo "octosql -o csv \"select path,score,'https://old.reddit.com/r/$subreddit/' as playlist_path from `../reddit_links.parquet` where lower(playlist_path) = '$subreddit' order by score desc \" > $subreddit.csv"
        end
    end | parallel -j8

    for subreddit in $subreddits
        sqlite-utils upsert --pk path --alter --csv --detect-types $reddit_db media $subreddit.csv
    end

    library tubeadd --safe --ignore-errors --force $reddit_db (sqlite-utils --raw-lines $reddit_db 'select path from media')
end
```

</details>

### Datasette

<details><summary>Explore `library` databases in your browser</summary>

    pip install datasette
    datasette tv.db

</details>

### Pipe to [mnamer](https://github.com/jkwill87/mnamer)

<details><summary>Rename poorly named files</summary>

    pip install mnamer
    mnamer --movie-directory ~/d/70_Now_Watching/ --episode-directory ~/d/70_Now_Watching/ \
        --no-overwrite -b (library watch -p fd -s 'path : McCloud')
    library fsadd ~/d/70_Now_Watching/

</details>

### Pipe to [lowcharts](https://github.com/juan-leon/lowcharts)

<details><summary>$ library watch -p f -col time_created | lowcharts timehist -w 80</summary>

    Matches: 445183.
    Each ∎ represents a count of 1896
    [2022-04-13 03:16:05] [151689] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
    [2022-04-19 07:59:37] [ 16093] ∎∎∎∎∎∎∎∎
    [2022-04-25 12:43:09] [ 12019] ∎∎∎∎∎∎
    [2022-05-01 17:26:41] [ 48817] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
    [2022-05-07 22:10:14] [ 36259] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
    [2022-05-14 02:53:46] [  3942] ∎∎
    [2022-05-20 07:37:18] [  2371] ∎
    [2022-05-26 12:20:50] [   517]
    [2022-06-01 17:04:23] [  4845] ∎∎
    [2022-06-07 21:47:55] [  2340] ∎
    [2022-06-14 02:31:27] [   563]
    [2022-06-20 07:14:59] [ 13836] ∎∎∎∎∎∎∎
    [2022-06-26 11:58:32] [  1905] ∎
    [2022-07-02 16:42:04] [  1269]
    [2022-07-08 21:25:36] [  3062] ∎
    [2022-07-15 02:09:08] [  9192] ∎∎∎∎
    [2022-07-21 06:52:41] [ 11955] ∎∎∎∎∎∎
    [2022-07-27 11:36:13] [ 50938] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
    [2022-08-02 16:19:45] [ 70973] ∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎∎
    [2022-08-08 21:03:17] [  2598] ∎

BTW, for some cols like time_deleted you'll need to specify a where clause so they aren't filtered out:

    $ library watch -p f -col time_deleted -w time_deleted'>'0 | lowcharts timehist -w 80

![video width](https://user-images.githubusercontent.com/7908073/184737808-b96fbe65-a1d9-43c2-b6b4-4bdfab592190.png)

![fps](https://user-images.githubusercontent.com/7908073/184738438-ee566a4b-2da0-4e6d-a4b3-9bfca036aa2a.png)

</details>

## Usage

{''.join(usage_details)}

<details><summary>Chicken mode</summary>


           ////////////////////////
          ////////////////////////|
         //////////////////////// |
        ////////////////////////| |
        |    _\/_   |   _\/_    | |
        |     )o(>  |  <)o(     | |
        |   _/ <\   |   /> \_   | |        just kidding :-)
        |  (_____)  |  (_____)  | |_
        | ~~~oOo~~~ | ~~~0oO~~~ |/__|
       _|====\_=====|=====_/====|_ ||
      |_|\_________ O _________/|_|||
       ||//////////|_|\\\\\\\\\\|| ||
       || ||       |\_\\        || ||
       ||/||        \\_\\       ||/||
       ||/||         \)_\)      ||/||
       || ||         \  O /     || ||
       ||             \  /      || LGB

                   \________/======
                   / ( || ) \\

</details>

You can expand all by running this in your browser console:

{expand_all_js}

"""

print(readme)
