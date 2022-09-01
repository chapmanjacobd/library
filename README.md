# lb: xk media library

A wise philosopher once told me, "[The future is autotainment](https://www.youtube.com/watch?v=F9sZFrsjPp0)".

Manage large media libraries. Similar to Plex but more minimalist. Primary usage is local filesystem but also supports some virtual constructs like tracking video playlists (eg. YouTube subscriptions) and browser tabs.

Required: `ffmpeg`

Recommended: `mpv`, `fish`, `firefox`

## Install

Linux recommended but [Windows setup instructions](./Windows.md) available.

    pip install xklb

    $ library
    xk media library [lb]

    local media subcommands:
      fsadd [extract, xr]                Create a local media database; Add folders
      subtitle                           Find subtitles for local media
      listen [lt]                        Listen to local media
      watch [wt]                         Watch local media
      filesystem [fs]                    Browse files

    online media subcommands:
      tubeadd [ta]                       Create a tube database; Add playlists
      tubelist [playlist, playlists]     List added playlists
      tubeupdate [tu]                    Get new videos for your saved playlists
      tubewatch [tw, tube, entries]      Watch the tube
      tubelisten [tl]                    Listen to the tube

    browser tabs subcommands:
      tabsadd                            Create a tabs database; Add URLs
      tabs [tb]                          Open your tabs for the day

## Quick Start -- watch online media on your PC

    wget https://github.com/chapmanjacobd/lb/raw/main/examples/mealtime.tw.db
    library tubewatch mealtime.tw.db

## Quick Start -- listen to online media on a chromecast group

    wget https://github.com/chapmanjacobd/lb/raw/main/examples/music.tl.db
    lb tubelisten music.tl.db -ct "House speakers"

## Start -- local media

### 1. Extract Metadata

For thirty terabytes of video the initial scan takes about four hours to complete. After that, rescans of the same path (or any subpaths) are much quicker--only new files will be read by `ffprobe`.

    lb fsadd tv.db ./video/folder/

![termtosvg](./examples/extract.svg)

### 2. Watch / Listen from local files

    lb wt tv.db                          # the default post-action is to do nothing after playing
    lb wt tv.db --post-action delete     # delete file after playing
    lb lt finalists.db --post-action=ask # ask to delete after playing

To stop playing just press Ctrl+C in either the terminal or mpv

## Start -- online media

### 1. Download Metadata

Download playlist and channel metadata. Break free of the YouTube algo~

    lb tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

[![termtosvg](./examples/tubeadd.svg "lb tubeadd example")](https://asciinema.org/a/BzplqNj9sCERH3A80GVvwsTTT)

And you can always add more later--even from different websites.

    lb tubeadd maker.db https://vimeo.com/terburg

To prevent mistakes the default configuration is to download metadata for only the most recent 20,000 videos per playlist/channel.

    lb tubeadd maker.db --yt-dlp-config playlistend=1000

Be aware that there are some YouTube Channels which have many items--for example the TEDx channel has about 180,000 videos. Some channels even have upwards of two million videos. More than you could likely watch in one sitting. On a high-speed connection (>500 Mbps), it can take up to five hours just to download the metadata for 180,000 videos.

#### 1a. Get new videos for saved playlists

Tubeupdate will go through all added playlists and fetch metadata of any new videos not previously seen.

    lb tubeupdate

### 2. Watch / Listen from websites

    lb tubewatch maker.db

To stop playing just press Ctrl+C in either the terminal or mpv

## Start -- tabs (visit websites on a schedule)

tabs provides a way to organize your visits to URLs that you want to visit every once in a while.

If you want to track _changes_ to websites over time there are better tools out there, like
`huginn`, `urlwatch`, or `changedetection.io`.

The use-case of tabs are websites that you know are going to change: subreddits, games, or tools that you want to use for a few minutes every certain frequency (eg. daily/weekly/monthly/quarterly/yearly).

### 1. Add your websites

    lb tabsadd --frequency monthly --category fun https://old.reddit.com/r/Showerthoughts/top/?sort=top&t=month https://old.reddit.com/r/RedditDayOf/top/?sort=top&t=month

### 2. Add lb tabs to cron

lb tabs is meant to run **once per day**. Here is how you would configure it with `crontab`:

    45 9 * * * DISPLAY=:0 lb tabs /home/my/tabs.db

You can also invoke tabs manually:

    lb tabs -L 1  # open one tab

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
    usage: lb watch [database] [optional args]

        If not specified, watch will try to read video.db in the working directory:

            lb watch

        Override the default player (mpv):

            lb does a lot of things to try to automatically use your preferred media player
            but if it doesn't guess right you can make it explicit:

            lb watch --player "vlc --vlc-opts"

        Cast to chromecast groups:

            lb watch --cast --cast-to "Office pair"
            lb watch -ct "Office pair"  # equivalent

            If you don't know the exact name of your chromecast group run `catt scan`

        Print instead of play:

            Generally speaking, you should always be able to add `-p` to check what the play queue
            will look like before playing--even while using many other option simultaneously.
            The results might lie when using `-OO` or `-OOO`.

            lb watch --print --limit 10  # print the next 10 files
            lb watch -p -L 10  # print the next 10 files
            lb watch -p  # this will print _all_ the media. be cautious about `-p` on an unfiltered set

            Printing modes

            lb watch -p    # print in a table
            lb watch -p p  # equivalent
            lb watch -p a  # print an aggregate report
            lb watch -p f  # print fields -- useful for piping to utilities like xargs or GNU Parallel

            Check if you have downloaded something before

            lb watch -u duration -p -s 'title'

            Print an aggregate report of deleted media

            lb watch -w is_deleted=1 -p a
            ╒═══════════╤══════════════╤═════════╤═════════╕
            │ path      │ duration     │ size    │   count │
            ╞═══════════╪══════════════╪═════════╪═════════╡
            │ Aggregate │ 14 days, 23  │ 50.6 GB │   29058 │
            │           │ hours and 42 │         │         │
            │           │ minutes      │         │         │
            ╘═══════════╧══════════════╧═════════╧═════════╛
            Total duration: 14 days, 23 hours and 42 minutes

            Print an aggregate report of media that has no duration information (likely corrupt media)

            lb watch -w 'duration is null' -p a

            Print a list of videos which have below 1280px resolution

            lb watch -w 'width<1280' -p f

            View how much time you have listened to music

            lb lt -w play_count'>'0 -p a

            See how much video you have

            lb watch video.db -p a
            ╒═══════════╤═════════╤═════════╤═════════╕
            │ path      │   hours │ size    │   count │
            ╞═══════════╪═════════╪═════════╪═════════╡
            │ Aggregate │  145769 │ 37.6 TB │  439939 │
            ╘═══════════╧═════════╧═════════╧═════════╛
            Total duration: 16 years, 7 months, 19 days, 17 hours and 25 minutes

            View all the columns

            lb watch -p -L 1 --cols '*'

            Open ipython with all of your media

            lb watch -vv -p --cols '*'
            ipdb> len(db_resp)
            462219

        Set the play queue size:

            By default the play queue is 120--long enough that you likely have not noticed
            but short enough that the program is snappy.

            If you want everything in your play queue you can use the aid of infinity.

            Pick your poison (these all do effectively the same thing):
            lb watch -L inf
            lb watch -l inf
            lb watch --queue inf
            lb watch -L 99999999999999999999999

            You may also want to restrict the play queue.
            For example, when you only want 1000 random files:

            lb watch -u random -L 1000

        Offset the play queue:

            You can also offset the queue. For example if you want to skip one or ten media:

            lb watch -S 10  # offset ten from the top of an ordered query

        Repeat

            lb listen                  # listen to 120 random songs (DEFAULT_PLAY_QUEUE)
            lb listen --limit 5        # listen to FIVE songs
            lb listen -l inf -u random # listen to random songs indefinitely
            lb listen -s infinite      # listen to songs from the band infinite

        Constrain media by search:

            Audio files have many tags to readily search through so metadata like artist,
            album, and even mood are included in search.
            Video files have less consistent metadata and so only paths are included in search.

            lb watch --include happy  # only matches will be included
            lb watch -s happy         # equivalent

            lb watch --exclude sad   # matches will be excluded
            lb watch -E sad          # equivalent

            Double spaces are parsed as one space

            -s '  ost'        # will match OST and not ghost
            -s toy story      # will match '/folder/toy/something/story.mp3'
            -s 'toy  story'    # will match more strictly '/folder/toy story.mp3'

        Constrain media by arbitrary SQL expressions:

            lb watch --where audio_count = 2  # media which have two audio tracks
            lb watch -w "language = 'eng'"    # media which have an English language tag
                                                (this could be audio _or_ subtitle)
            lb watch -w subtitle_count=0      # media that doesn't have subtitles

        Constrain media to duration (in minutes):

            lb watch --duration 20

            lb watch -d 6  # 6 mins ±10 percent (ie. between 5 and 7 mins)
            lb watch -d-6  # less than 6 mins
            lb watch -d+6  # more than 6 mins

            Can be specified multiple times:

            lb watch -d+5 -d-7  # should be similar to -d 6

            If you want exact time use `where`

            lb watch --where 'duration=6*60'

        Constrain media to file size (in megabytes):

            lb watch --size 20

            lb watch -z 6  # 6 MB ±10 percent (ie. between 5 and 7 MB)
            lb watch -z-6  # less than 6 MB
            lb watch -z+6  # more than 6 MB

        Constrain media by throughput:

            Bitrate information is not explicitly saved.
            You can use file size and duration as a proxy for throughput:

            lb wt -w 'size/duration<50000'

        Constrain media to portrait orientation video:

            lb watch --portrait
            lb watch -w 'width<height' # equivalent

        Specify media play order:

            lb watch --sort duration   # play shortest media first
            lb watch -u duration desc  # play longest media first

            You can use multiple SQL ORDER BY expressions

            lb watch -u subtitle_count > 0 desc # play media that has at least one subtitle first

        Play media in order (similarly named episodes):

            lb watch --play-in-order

            There are multiple strictness levels of --play-in-order.
            If things aren't playing in order try adding more `O`s:

            lb watch -O    # normal
            lb watch -OO   # slower, more complex algorithm
            lb watch -OOO  # strict

        Post-actions -- choose what to do after playing:

            lb watch --post-action delete  # delete file after playing
            lb watch -k ask  # ask after each whether to keep or delete
            lb watch -k askkeep  # ask after each whether to move to a keep folder or delete

            The default location is ./keep/ (relative to each individual media file)
            You can change this by explicitly setting an *absolute* `keep-dir` path:

            lb watch -k askkeep --keep-dir /home/my/music/keep/

        Experimental options:

            Duration to play (in seconds) while changing the channel

            lb watch --interdimensional-cable 40
            lb watch -4dtv 40

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

I do this instead of copy-on-write duplication because I want deletions to stick (when I press the next button in the car I delete the song from my curated universe).

    function mrmusic
        rsync -a --remove-source-files --files-from=(
            lb lt ~/lb/audio.db -s /mnt/d/80_Now_Listening/ -p f \
            --moved /mnt/d/80_Now_Listening/ /mnt/d/ | psub
        ) /mnt/d/80_Now_Listening/ /mnt/d/

        rsync -a --remove-source-files --files-from=(
            lb lt ~/lb/audio.db -w play_count=0 -u random -L 1200 -p f \
            --moved /mnt/d/ /mnt/d/80_Now_Listening/ | psub
        ) /mnt/d/ /mnt/d/80_Now_Listening/
    end

### TODOs (PRs welcome)

- all: extracts switch to https://sqlite-utils.datasette.io/en/latest/python-api.html#adding-columns-automatically-on-insert-update
- tube: basic tests
- tube: make sure playlistless media doesn't save to the playlists table
- all: verify things work on Windows
- all: more test coverage -- https://hypothesis.readthedocs.io/en/latest/quickstart.html
- all: follow yt-dlp print arg syntax
- all: follow fd-find size arg syntax
- all: remove pandas dependency?
- fs: split_by_silence without modifying files
- fs: support subs/ folder
