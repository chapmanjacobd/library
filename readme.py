from xklb.fs_actions import fs_actions_usage
from xklb.lb import lb_usage

print(
    f"""# lb: xk media library

A wise philosopher once told me, "[The future is autotainment](https://www.youtube.com/watch?v=F9sZFrsjPp0)".

Manage large media libraries. Similar to Plex but more minimalist.
Primary usage is local filesystem but also supports some virtual constructs like
tracking video playlists (eg. YouTube subscriptions) or daily browser tabs.

Required: `ffmpeg`

Recommended: `mpv`, `fish`, `firefox`

## Install

Linux recommended but [Windows setup instructions](./Windows.md) available.

    pip install xklb

    $ library
    {lb_usage()}

## Quick Start -- watch online media on your PC

    wget https://github.com/chapmanjacobd/lb/raw/main/examples/mealtime.tw.db
    library tubewatch mealtime.tw.db

## Quick Start -- listen to online media on a chromecast group

    wget https://github.com/chapmanjacobd/lb/raw/main/examples/music.tl.db
    library tubelisten music.tl.db -ct "House speakers"

## Start -- local media

### 1. Extract Metadata

For thirty terabytes of video the initial scan takes about four hours to complete.
After that, subsequent scans of the path (or any subpaths) are much quicker--only
new files will be read by `ffprobe`.

    library fsadd tv.db ./video/folder/

![termtosvg](./examples/extract.svg)

### 2. Watch / Listen from local files

    library wt tv.db                          # the default post-action is to do nothing
    library wt tv.db --post-action delete     # delete file after playing
    library lt finalists.db --post-action=ask # ask whether to delete after playing

To stop playing press Ctrl+C in either the terminal or mpv

## Start -- online media

### 1. Download Metadata

Download playlist and channel metadata. Break free of the YouTube algo~

    library tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

[![termtosvg](./examples/tubeadd.svg "library tubeadd example")](https://asciinema.org/a/BzplqNj9sCERH3A80GVvwsTTT)

And you can always add more later--even from different websites.

    library tubeadd maker.db https://vimeo.com/terburg

To prevent mistakes the default configuration is to download metadata for only
the most recent 20,000 videos per playlist/channel.

    library tubeadd maker.db --yt-dlp-config playlistend=1000

Be aware that there are some YouTube Channels which have many items--for example
the TEDx channel has about 180,000 videos. Some channels even have upwards of
two million videos. More than you could likely watch in one sitting.
On a high-speed connection (>500 Mbps), it can take up to five hours to download
the metadata for 180,000 videos.

#### 1a. Get new videos for saved playlists

Tubeupdate will go through the list of added playlists and fetch metadata for
any videos not previously seen.

    library tubeupdate

### 2. Watch / Listen from websites

    library tubewatch maker.db

To stop playing press Ctrl+C in either the terminal or mpv

## Start -- tabs (visit websites on a schedule)

tabs is a way to organize your visits to URLs that you want to visit every once in a while.

If you want to track _changes_ to websites over time there are better tools out there, like
`huginn`, `urlwatch`, or `changedetection.io`.

The use-case of tabs are websites that you know are going to change: subreddits, games,
or tools that you want to use for a few minutes daily, weekly, monthly, quarterly, or yearly.

### 1. Add your websites

    library tabsadd --frequency monthly --category fun https://old.reddit.com/r/Showerthoughts/top/?sort=top&t=month https://old.reddit.com/r/RedditDayOf/top/?sort=top&t=month

### 2. Add library tabs to cron

library tabs is meant to run **once per day**. Here is how you would configure it with `crontab`:

    45 9 * * * DISPLAY=:0 library tabs /home/my/tabs.db

Or with `systemd`:

    ~/.config/systemd/user/tabs.service
    [Unit]
    Description=xklb daily browser tabs

    [Service]
    Environment="DISPLAY=:0"
    ExecStart="library" "tabs" "/home/xk/lb/tabs.db"
    RemainAfterExit=no

    ~/.config/systemd/user/tabs.timer
    [Unit]
    Description=xklb daily browser tabs

    [Timer]
    Persistent=yes
    OnCalendar=*-*-* 9:58
    RemainAfterElapse=yes

    systemctl --user daemon-reload
    systemctl --user enable --now tabs.service

You can also invoke tabs manually:

    library tabs -L 1  # open one tab

## Things to know.db

When the database file path is not specified, `video.db` will be created / used.

    library fsadd ./tv/

The same for audio: `audio.db` will be created / used.

    library fsadd --audio ./music/

Likewise, `fs.db` from:

    library fsadd --filesystem /any/path/

If you want to specify more than one directory you need to mention the db file explicitly.

    library fsadd --filesystem one/
    library fsadd --filesystem fs.db one/ two/

Organize via separate databases.

    library fsadd --audio both.db ./audiobooks/ ./podcasts/
    library fsadd --audio audiobooks.db ./audiobooks/
    library fsadd --audio podcasts.db ./podcasts/ ./another/more/secret/podcasts_folder/

## Usage

    $ library watch -h
    usage: {fs_actions_usage('watch', 'video.db')}

### You can pipe stuff

#### [lowcharts](https://github.com/juan-leon/lowcharts)

    $ wt-dev -p f -col time_created | lowcharts timehist -w 80
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

![video width](https://user-images.githubusercontent.com/7908073/184737808-b96fbe65-a1d9-43c2-b6b4-4bdfab592190.png)

![fps](https://user-images.githubusercontent.com/7908073/184738438-ee566a4b-2da0-4e6d-a4b3-9bfca036aa2a.png)

#### rsync

I use rsync to move files instead of copy-on-write duplication because I want deletions to stick.
When I press the next button in the car I delete the song from my curated universe.

    function mrmusic
        rsync -a --remove-source-files --files-from=(
            library lt ~/lb/audio.db -s /mnt/d/80_Now_Listening/ -p f \
            --moved /mnt/d/80_Now_Listening/ /mnt/d/ | psub
        ) /mnt/d/80_Now_Listening/ /mnt/d/

        rsync -a --remove-source-files --files-from=(
            library lt ~/lb/audio.db -w play_count=0 -u random -L 1200 -p f \
            --moved /mnt/d/ /mnt/d/80_Now_Listening/ | psub
        ) /mnt/d/ /mnt/d/80_Now_Listening/
    end

#### Datasette

Explore `library` databases in your browser

    pip install datasette
    datasette tv.db

### TODOs (PRs welcome)

- test linux: now, next, stop
- test windows: now, next, stop
- fs: ebook and documents
- tube: make sure playlistless media doesn't save to the playlists table
- tube: basic tests
- all: more test coverage -- https://hypothesis.readthedocs.io/en/latest/quickstart.html
- all: follow yt-dlp print arg syntax
- all: follow fd-find size arg syntax
- fs: split_by_silence without modifying files
"""
)
