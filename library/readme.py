from library import __main__
from library.utils import consts

usage_details_md = []


def _portable_usage(text: str) -> str:
    return text.replace(consts.DEFAULT_MPV_LISTEN_SOCKET, "$XDG_RUNTIME_DIR/mpv_socket").replace(
        consts.DEFAULT_MPV_WATCH_SOCKET,
        "~/.config/mpv/socket",
    )


for category, category_progs in __main__._command_catalog():
    usage_details_md.append(f"\n### {category}\n")

    for canonical_command, prog_description in category_progs:
        prog_usage = __main__.command_usage(canonical_command)

        if prog_usage:
            prog_usage = _portable_usage(__main__.canonicalize_usage_for_command(prog_usage, canonical_command))
            usage_details_md.append(
                f"""
###### {canonical_command}

<details><summary>{prog_description}</summary>

    $ library {canonical_command} -h
    usage: {prog_usage.replace('%%', '%')}

</details>
""",
            )

expand_all_js = """```js
(() => { const readmeDiv = document.querySelector("article"); const detailsElements = readmeDiv.getElementsByTagName("details"); for (let i = 0; i < detailsElements.length; i++) { detailsElements[i].setAttribute("open", "true"); } })();
```"""

readme = rf"""# library (media toolkit)

A wise philosopher once told me: "the future is [autotainment](https://www.youtube.com/watch?v=F9sZFrsjPp0)".

Manage and curate large media libraries. An index for your archive.
Primary usage is local filesystem but also supports some virtual constructs like
tracking online video playlists (eg. YouTube subscriptions) and scheduling browser tabs.

<img align="right" width="300" height="600" src="https://raw.githubusercontent.com/chapmanjacobd/library/main/.github/examples/art.avif" />

[![Downloads](https://static.pepy.tech/badge/library)](https://pepy.tech/project/library)

## Getting started

<details><summary>Install</summary>

Linux recommended but [Windows setup instructions](https://github.com/chapmanjacobd/library/blob/main/.github/Windows.md) available.

    pip install library

Mac OS is also supported.

### External dependencies

Required: `ffmpeg`

Some features work better with: `mpv`, `fd-find`, `fish`

Optional Python extras are grouped under `library[deluxe]`. This includes
`gallery-dl` (used by `database add gallery`), `internetarchive` (used for
Internet Archive downloads), and `cdx_toolkit` (used by the
`--webcache`/`--wayback` CDX extractor):

    pip install "library[deluxe]"

Torrent metadata commands (`database add torrents` and `torrent dump`) require
the `libtorrent` Python bindings. They are included by `library[deluxe]` on
Python 3.12 and 3.13. On Python 3.14, libtorrent-rasterbar bindings are
usually provided by distro packages rather than PyPI:

* Debian/Ubuntu: `sudo apt install python3-libtorrent`
* Fedora: `sudo dnf install rb_libtorrent-python3`
* macOS/Homebrew: `brew install libtorrent-rasterbar`

The Debian, Fedora, and Homebrew packages are built for their system or
Homebrew Python and are not importable from a separate uv virtualenv. There
is no official Scoop package for the Python bindings; on Windows, use Python
3.13 and `pip install "library[deluxe]"`.

</details>

<details><summary>Local media</summary>

### 1. Extract Metadata

For thirty terabytes of video the initial scan takes about four hours to complete.
After that, subsequent scans of the path (or any subpaths) are much quicker--only
new files are read by `ffprobe`.

    library database add filesystem tv.db ./video/folder/

![termtosvg](https://raw.githubusercontent.com/chapmanjacobd/library/main/.github/examples/extract.svg)

### 2. Watch / Listen from local files

    library play video tv.db                           # the default post-action is to do nothing
    library play video tv.db --post-action delete      # delete file after playing
    library play audio finalists.db -k ask_delete      # ask whether to delete file after playing

To stop playing press Ctrl+C in either the terminal or mpv

</details>

<details><summary>Online media</summary>

### 1. Download Metadata

Download playlist and channel metadata. Break free of the YouTube algo~

    library database add video educational.db https://www.youtube.com/c/BranchEducation/videos

[![termtosvg](https://raw.githubusercontent.com/chapmanjacobd/library/main/.github/examples/tubeadd.svg "library database add video example")](https://asciinema.org/a/BzplqNj9sCERH3A80GVvwsTTT)

And you can add more at any time--even from different websites.

    library database add video maker.db https://vimeo.com/terburg

To prevent mistakes the default configuration is to download metadata for only
the most recent 20,000 videos per playlist/channel.

    library database add video maker.db --extractor-config playlistend=1000

Be aware that there are some YouTube Channels which have many items--for example
the TEDx channel has about 180,000 videos. Some channels even have upwards of
two million videos. More than you could likely watch in one sitting--maybe even one lifetime.
On a high-speed connection (>500 Mbps), it can take up to five hours to download
the metadata for 180,000 videos.

TIP! If you often copy and paste many URLs you can paste line-delimited text as arguments via a subshell. For example, in `fish` shell with [cb](https://github.com/niedzielski/cb):

    library database add video my.db (cb)

Or in BASH:

    library database add video my.db $(xclip -selection c)

#### 1a. Get new videos for saved playlists

Tubeupdate goes through the list of stored playlists and fetches metadata for
any videos not seen before.

    library database update video tube.db

### 2. Watch / Listen from websites

    library play video maker.db

To stop playing press Ctrl+C in either the terminal or mpv

</details>

<details><summary>List all subcommands</summary>

Commands are organized by workflow. Use `database` (or `db`) for database
operations, `filesystem` (or `fs`) for filesystem operations, `document` (or
`doc`/`docs`) for document operations, and `file` (or `files`) for file
operations. The `ls` alias can be used for nested list commands. Resource group
names and their aliases take precedence over flat command names, so a few former
flat commands are now only reachable through a group (for example
`filesystem list`, `captions`, `table markdown`, `tabs open`,
`links extract`, `text extract`, and `torrent info`).

    $ library
    {__main__.usage()}

</details>

## Examples

### Watch online media on your PC

    wget https://github.com/chapmanjacobd/library-examples/raw/main/mealtime.tw.db
    library play video mealtime.tw.db --random --duration 30m

### Listen to online media on a chromecast group

    wget https://github.com/chapmanjacobd/library-examples/raw/main/music.tl.db
    library play audio music.tl.db -ct "House speakers" --random

### Hook into HackerNews

    wget https://github.com/chapmanjacobd/hn_mining/raw/main/hackernews_only_direct.tw.db
    library play video hackernews_only_direct.tw.db --random --ignore-errors

### Organize via separate databases

    library database add filesystem --audio audiobooks.db ./audiobooks/
    library database add filesystem --audio podcasts.db ./podcasts/ ./another/more/secret/podcasts_folder/

    # merge later if you want
    library database merge --pk path -t playlists,media audiobooks.db podcasts.db both.db

    # or split
    library database merge --pk path -t playlists,media both.db audiobooks.db -w 'path like "%/audiobooks/%"'
    library database merge --pk path -t playlists,media both.db podcasts.db -w 'path like "%/podcasts%"'

## Guides

### Music alarm clock

<details><summary>via termux crontab</summary>

Wake up to your own music

    30 7 * * * library play audio ./audio.db

Wake up to your own music _only when you are *not* home_ (computer on local IP)

    30 7 * * * timeout 0.4 nc -z 192.168.1.12 22 || library play audio --random

Wake up to your own music on your Chromecast speaker group _only when you are home_

    30 7 * * * ssh 192.168.1.12 library play audio --cast --cast-to "Bedroom pair"

</details>


### Browser Tabs

<details><summary>Visit websites on a schedule</summary>

`tabs` is a way to organize your visits to URLs that you want to remember every once in a while.

The main benefit of tabs is that you can have a large amount of tabs saved (say 500 monthly tabs) and only the smallest
amount of tabs to satisfy that goal (500/30) tabs open each day. 17 tabs per day seems manageable--500 all at once does not.

The use-case of tabs are websites that you know are going to change: subreddits, games,
or tools that you want to use for a few minutes daily, weekly, monthly, quarterly, or yearly.

### 1. Add your websites

    library database add tabs tabs.db --frequency monthly --category fun \
        https://old.reddit.com/r/Showerthoughts/top/?sort=top&t=month \
        https://old.reddit.com/r/RedditDayOf/top/?sort=top&t=month

### 2. Add library tabs to cron

library tabs open runs **once per day**. Configure it with `crontab`:

    45 9 * * * DISPLAY=:0 library tabs open /home/my/tabs.db

Or with `systemd`:

    tee ~/.config/systemd/user/tabs.service
    [Unit]
    Description=library daily browser tabs

    [Service]
    Type=simple
    RemainAfterExit=no
    Environment="DISPLAY=:0"
    ExecStart=library tabs open /home/my/tabs.db

    tee ~/.config/systemd/user/tabs.timer
    [Unit]
    Description=library daily browser tabs timer

    [Timer]
    Persistent=yes
    OnCalendar=*-*-* 9:58

    [Install]
    WantedBy=timers.target

    systemctl --user daemon-reload
    systemctl --user enable --now tabs.service

You can also invoke tabs manually:

    library tabs open tabs.db -L 1  # open one tab

Incremental surfing. 📈🏄 totally rad!

</details>

### Find large folders

<details><summary>Curate with library folder large</summary>

If you are looking for candidate folders for curation (ie. you need space but don't want to buy another hard drive).
The folder large subcommand serves that purpose:

    $ library folder large fs/d.db

Filter by folder depth (similar to QDirStat or WizTree)

    $ library folder large --depth=3 audio.db

There is also a flag to prioritize folders which have many files which have been deleted (for example you delete songs you don't like--you can see who wrote those songs and delete all their other songs...)

    $ library folder large --sort-groups-by deleted audio.db

The play subcommands also support this functionality:

    $ library play video --big-dirs ./my.db
    $ library play video -B  # shorthand equivalent

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

    library database add video --safe --ignore-errors --force $reddit_db (sqlite-utils --raw-lines $reddit_db 'select path from media')
end
```

</details>

### Datasette

<details><summary>Explore `library` databases in your browser</summary>

    pip install datasette
    datasette tv.db

</details>

### Pipe to [fzf](https://github.com/junegunn/fzf)

<details><summary>Choose a video to play</summary>

You can use fzf in a subshell to choose a specific video from 1000 random options

    library play video ~/lb/video.db (library play video ~/lb/video.db -pf --random -L 1000 | fzf)

</details>

### Pipe to [mnamer](https://github.com/jkwill87/mnamer)

<details><summary>Rename poorly named files</summary>

    pip install mnamer
    mnamer --movie-directory ~/d/70_Now_Watching/ --episode-directory ~/d/70_Now_Watching/ \
        --no-overwrite -b (library play video -p fd -s 'path : McCloud')
    library database add filesystem ~/d/70_Now_Watching/

</details>

### Pipe to [lowcharts](https://github.com/juan-leon/lowcharts)

<details><summary>$ library play video -p f -col time_created | lowcharts timehist -w 80</summary>

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

    $ library play video -p f -col time_deleted -w time_deleted'>'0 | lowcharts timehist -w 80

![video width](https://user-images.githubusercontent.com/7908073/184737808-b96fbe65-a1d9-43c2-b6b4-4bdfab592190.png)

![fps](https://user-images.githubusercontent.com/7908073/184738438-ee566a4b-2da0-4e6d-a4b3-9bfca036aa2a.png)

</details>

## Usage

{''.join(usage_details_md)}

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


    TypeError: Retry.__init__() got an unexpected keyword argument 'backoff_jitter'
    pip install --upgrade --ignore-installed urllib3 requests

</details>

You can expand all by running this in your browser console:

{expand_all_js}

Be sure to check out [https://www.unli.xyz/diskprices/](https://www.unli.xyz/diskprices/) for all your storage needs

"""

print(readme)
