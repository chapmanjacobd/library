download = r"""library download database [--prefix /mnt/d/] --video | --audio

    Download stuff in a random order.

        library download dl.db --prefix ~/output/path/root/

    Download stuff in a random order, limited to the specified playlist URLs.

        library download dl.db https://www.youtube.com/c/BlenderFoundation/videos

    Files will be saved to <lb download prefix>/<lb download category>/

        For example:
        library dladd Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    Print list of queued up downloads

        library download --print

    Print list of saved playlists

        library playlists dl.db -p a

    Print download queue groups

        library download-status audio.db
        ╒═════════════════════╤════════════╤══════════════════╤════════════════════╤══════════╕
        │ category            │ ie_key     │ duration         │   never_downloaded │   errors │
        ╞═════════════════════╪════════════╪══════════════════╪════════════════════╪══════════╡
        │ 81_New_Music        │ Soundcloud │                  │                 10 │        0 │
        ├─────────────────────┼────────────┼──────────────────┼────────────────────┼──────────┤
        │ 81_New_Music        │ Youtube    │ 10 days, 4 hours │                  1 │     2555 │
        │                     │            │ and 20 minutes   │                    │          │
        ├─────────────────────┼────────────┼──────────────────┼────────────────────┼──────────┤
        │ Playlist-less media │ Youtube    │ 7.68 minutes     │                 99 │        1 │
        ╘═════════════════════╧════════════╧══════════════════╧════════════════════╧══════════╛
"""

block = r"""library block database [playlists ...]

    Blocklist specific URLs (eg. YouTube channels, etc). With YT URLs this will block
    videos from the playlist uploader

        library block dl.db https://annoyingwebsite/etc/

    Use with the all-deleted-playlists flag to delete any previously downloaded files from the playlist uploader

        library block dl.db --all-deleted-playlists https://annoyingwebsite/etc/
"""

fsadd = """library fsadd [--audio | --video | --image |  --text | --filesystem] -c CATEGORY [database] paths ...

    The default database type is video:
        library fsadd tv.db ./tv/
        library fsadd --video tv.db ./tv/  # equivalent

    You can also create audio databases. Both audio and video use ffmpeg to read metadata:
        library fsadd --audio audio.db ./music/

    Image uses ExifTool:
        library fsadd --image image.db ./photos/

    Text will try to read files and save the contents into a searchable database:
        library fsadd --text text.db ./documents_and_books/

    Create a text database and scan with OCR and speech-recognition:
        library fsadd --text --ocr --speech-recognition ocr.db ./receipts_and_messages/

    Create a video database and read internal/external subtitle files into a searchable database:
        library fsadd --scan-subtitles tv.search.db ./tv/ ./movies/

    Decode media to check for corruption (slow):
        library fsadd --check-corrupt 100 tv.db ./tv/  # scan through 100 percent of each file to evaluate how corrupt it is (very slow)
        library fsadd --check-corrupt   1 tv.db ./tv/  # scan through 1 percent of each file to evaluate how corrupt it is (takes about one second per file)
        library fsadd --check-corrupt   5 tv.db ./tv/  # scan through 1 percent of each file to evaluate how corrupt it is (takes about ten seconds per file)

        library fsadd --check-corrupt   5 --delete-corrupt 30 tv.db ./tv/  # scan 5 percent of each file to evaluate how corrupt it is, if 30 percent or more of those checks fail then the file is deleted

        nb: the behavior of delete-corrupt changes between full and partial scan
        library fsadd --check-corrupt  99 --delete-corrupt  1 tv.db ./tv/  # partial scan 99 percent of each file to evaluate how corrupt it is, if 1 percent or more of those checks fail then the file is deleted
        library fsadd --check-corrupt 100 --delete-corrupt  1 tv.db ./tv/  # full scan each file to evaluate how corrupt it is, if there is _any_ corruption then the file is deleted

    Normally only relevant filetypes are included. You can scan all files with this flag:
        library fsadd --scan-all-files mixed.db ./tv-and-maybe-audio-only-files/
        # I use that with this to keep my folders organized:
        library watch -w 'video_count=0 and audio_count>=1' -pf mixed.db | parallel mv {} ~/d/82_Audiobooks/

    Remove path roots with --force
        library fsadd audio.db /mnt/d/Youtube/
        [/mnt/d/Youtube] Path does not exist

        library fsadd --force audio.db /mnt/d/Youtube/
        [/mnt/d/Youtube] Path does not exist
        [/mnt/d/Youtube] Building file list...
        [/mnt/d/Youtube] Marking 28932 orphaned metadata records as deleted
"""

fsupdate = """library fsupdate database

    Update each path previously saved:

        library fsupdate database
"""

hnadd = """library hnadd [--oldest] database

    Fetch latest stories first:

        library hnadd hn.db -v
        Fetching 154873 items (33212696 to 33367569)
        Saving comment 33367568
        Saving comment 33367543
        Saving comment 33367564
        ...

    Fetch oldest stories first:

        library hnadd --oldest hn.db
"""


def play(action) -> str:
    return f"""library {action} [database] [optional args]

    Control playback:
        To stop playback press Ctrl-C in either the terminal or mpv

        Create global shortcuts in your desktop environment by sending commands to mpv_socket:
        echo 'playlist-next force' | socat - /tmp/mpv_socket

    Override the default player (mpv):
        library does a lot of things to try to automatically use your preferred media player
        but if it doesn't guess right you can make it explicit:
        library {action} --player "vlc --vlc-opts"

    Cast to chromecast groups:
        library {action} --cast --cast-to "Office pair"
        library {action} -ct "Office pair"  # equivalent
        If you don't know the exact name of your chromecast group run `catt scan`

    Play media in order (similarly named episodes):
        library {action} --play-in-order
        There are multiple strictness levels of --play-in-order:
        library {action} -O    # equivalent
        library {action} -OO   # above, plus ignores most filters
        library {action} -OOO  # above, plus ignores fts and (include/exclude) filter during ordinal search
        library {action} -OOOO # above, plus starts search with parent folder

        library {action} --related  # similar to -O but uses fts to find similar content
        library {action} -R         # equivalent
        library {action} -RR        # above, plus ignores most filters

        library {action} --cluster  # cluster-sort to put similar paths closer together

        All of these options can be used together but it will be a bit slow and the results might be mid-tier
        as multiple different algorithms create a muddied signal (too many cooks in the kitchen):
        library {action} -RRCOO

    Filter media by file siblings of parent directory:
        library {action} --sibling   # only include files which have more than or equal to one sibling
        library {action} --solo      # only include files which are alone by themselves

        `--sibling` is just a shortcut for `--lower 2`; `--solo` is `--upper 1`
        library {action} --sibling --solo      # you will always get zero records here
        library {action} --lower 2 --upper 1   # equivalent

        You can be more specific via the `--upper` and `--lower` flags
        library {action} --lower 3   # only include files which have three or more siblings
        library {action} --upper 3   # only include files which have fewer than three siblings
        library {action} --lower 3 --upper 3   # only include files which are three siblings inclusive
        library {action} --lower 12 --upper 25 -OOO  # on my machine this launches My Mister 2018

    Play recent partially-watched videos (requires mpv history):
        library {action} --partial       # play newest first

        library {action} --partial old   # play oldest first
        library {action} -P o            # equivalent

        library {action} -P p            # sort by percent remaining
        library {action} -P t            # sort by time remaining
        library {action} -P s            # skip partially watched (only show unseen)

        The default time used is "last-viewed" (ie. the most recent time you closed the video)
        If you want to use the "first-viewed" time (ie. the very first time you opened the video)
        library {action} -P f            # use watch_later file creation time instead of modified time

        You can combine most of these options, though some will be overridden by others.
        library {action} -P fo           # this means "show the oldest videos using the time I first opened them"
        library {action} -P pt           # weighted remaining (percent * time remaining)

    Print instead of play:
        library {action} --print --limit 10  # print the next 10 files
        library {action} -p -L 10  # print the next 10 files
        library {action} -p  # this will print _all_ the media. be cautious about `-p` on an unfiltered set

        Printing modes
        library {action} -p    # print as a table
        library {action} -p a  # print an aggregate report
        library {action} -p b  # print a bigdirs report (see library bigdirs -h for more info)
        library {action} -p f  # print fields (defaults to path; use --cols to change)
                               # -- useful for piping paths to utilities like xargs or GNU Parallel

        library {action} -p d  # mark deleted
        library {action} -p w  # mark watched

        Some printing modes can be combined
        library {action} -p df  # print files for piping into another program and mark them as deleted within the db
        library {action} -p bf  # print fields from bigdirs report

        Check if you have downloaded something before
        library {action} -u duration -p -s 'title'

        Print an aggregate report of deleted media
        library {action} -w time_deleted!=0 -p=a
        ╒═══════════╤══════════════╤═════════╤═════════╕
        │ path      │ duration     │ size    │   count │
        ╞═══════════╪══════════════╪═════════╪═════════╡
        │ Aggregate │ 14 days, 23  │ 50.6 GB │   29058 │
        │           │ hours and 42 │         │         │
        │           │ minutes      │         │         │
        ╘═══════════╧══════════════╧═════════╧═════════╛
        Total duration: 14 days, 23 hours and 42 minutes

        Print an aggregate report of media that has no duration information (ie. online or corrupt local media)
        library {action} -w 'duration is null' -p=a

        Print a list of filenames which have below 1280px resolution
        library {action} -w 'width<1280' -p=f

        Print media you have partially viewed with mpv
        library {action} --partial -p
        library {action} -P -p  # equivalent
        library {action} -P -p f --cols path,progress,duration  # print CSV of partially watched files
        library {action} --partial -pa  # print an aggregate report of partially watched files

        View how much time you have {action}ed
        library {action} -w play_count'>'0 -p=a

        See how much video you have
        library {action} video.db -p=a
        ╒═══════════╤═════════╤═════════╤═════════╕
        │ path      │   hours │ size    │   count │
        ╞═══════════╪═════════╪═════════╪═════════╡
        │ Aggregate │  145769 │ 37.6 TB │  439939 │
        ╘═══════════╧═════════╧═════════╧═════════╛
        Total duration: 16 years, 7 months, 19 days, 17 hours and 25 minutes

        View all the columns
        library {action} -p -L 1 --cols '*'

        Open ipython with all of your media
        library {action} -vv -p --cols '*'
        ipdb> len(media)
        462219

    Set the play queue size:
        By default the play queue is 120--long enough that you likely have not noticed
        but short enough that the program is snappy.

        If you want everything in your play queue you can use the aid of infinity.
        Pick your poison (these all do effectively the same thing):
        library {action} -L inf
        library {action} -l inf
        library {action} --queue inf
        library {action} -L 99999999999999999999999

        You may also want to restrict the play queue.
        For example, when you only want 1000 random files:
        library {action} -u random -L 1000

    Offset the play queue:
        You can also offset the queue. For example if you want to skip one or ten media:
        library {action} --skip 10        # offset ten from the top of an ordered query

    Repeat
        library {action}                  # listen to 120 random songs (DEFAULT_PLAY_QUEUE)
        library {action} --limit 5        # listen to FIVE songs
        library {action} -l inf -u random # listen to random songs indefinitely
        library {action} -s infinite      # listen to songs from the band infinite

    Constrain media by search:
        Audio files have many tags to readily search through so metadata like artist,
        album, and even mood are included in search.
        Video files have less consistent metadata and so only paths are included in search.
        library {action} --include happy  # only matches will be included
        library {action} -s happy         # equivalent
        library {action} --exclude sad    # matches will be excluded
        library {action} -E sad           # equivalent

        Search only the path column
        library {action} -O -s 'path : mad max'
        library {action} -O -s 'path : "mad max"' # add "quotes" to be more strict

        Double spaces are parsed as one space
        library {action} -s '  ost'        # will match OST and not ghost
        library {action} -s toy story      # will match '/folder/toy/something/story.mp3'
        library {action} -s 'toy  story'   # will match more strictly '/folder/toy story.mp3'

        You can search without -s but it must directly follow the database due to how argparse works
        library {action} my.db searching for something

    Constrain media by arbitrary SQL expressions:
        library {action} --where audio_count = 2  # media which have two audio tracks
        library {action} -w "language = 'eng'"    # media which have an English language tag
                                                    (this could be audio _or_ subtitle)
        library {action} -w subtitle_count=0      # media that doesn't have subtitles

    Constrain media to duration (in minutes):
        library {action} --duration 20
        library {action} -d 6  # 6 mins ±10 percent (ie. between 5 and 7 mins)
        library {action} -d-6  # less than 6 mins
        library {action} -d+6  # more than 6 mins

        Duration can be specified multiple times:
        library {action} -d+5 -d-7  # should be similar to -d 6

        If you want exact time use `where`
        library {action} --where 'duration=6*60'

    Constrain media to file size (in megabytes):
        library {action} --size 20
        library {action} -S 6  # 6 MB ±10 percent (ie. between 5 and 7 MB)
        library {action} -S-6  # less than 6 MB
        library {action} -S+6  # more than 6 MB

    Constrain media by time_created / time_played / time_deleted / time_modified:
        library {action} --created-within '3 days'
        library {action} --created-before '3 years'

    Constrain media by throughput:
        Bitrate information is not explicitly saved.
        You can use file size and duration as a proxy for throughput:
        library {action} -w 'size/duration<50000'

    Constrain media to portrait orientation video:
        library {action} --portrait
        library {action} -w 'width<height' # equivalent

    Constrain media to duration of videos which match any size constraints:
        library {action} --duration-from-size +700 -u 'duration desc, size desc'

    Constrain media to online-media or local-media:
        Not to be confused with only local-media which is not "offline" (ie. one HDD disconnected)
        library {action} --online-media-only
        library {action} --online-media-only -i  # and ignore playback errors (ie. YouTube video deleted)
        library {action} --local-media-only

    Specify media play order:
        library {action} --sort duration   # play shortest media first
        library {action} -u duration desc  # play longest media first
        You can use multiple SQL ORDER BY expressions
        library {action} -u 'subtitle_count > 0 desc' # play media that has at least one subtitle first

    Post-actions -- choose what to do after playing:
        library {action} --post-action keep    # do nothing after playing (default)
        library {action} -k delete             # delete file after playing
        library {action} -k softdelete         # mark deleted after playing

        library {action} -k ask_keep           # ask whether to keep after playing
        library {action} -k ask_delete         # ask whether to delete after playing

        library {action} -k move               # move to "keep" dir after playing
        library {action} -k ask_move           # ask whether to move to "keep" folder
        The default location of the keep folder is ./keep/ (relative to the played media file)
        You can change this by explicitly setting an *absolute* `keep-dir` path:
        library {action} -k ask_move --keep-dir /home/my/music/keep/

        library {action} -k ask_move_or_delete # ask after each whether to move to "keep" folder or delete

    Experimental options:
        Duration to play (in seconds) while changing the channel
        library {action} --interdimensional-cable 40
        library {action} -4dtv 40

        Playback multiple files at once
        library {action} --multiple-playback    # one per display; or two if only one display detected
        library {action} --multiple-playback 4  # play four media at once, divide by available screens
        library {action} -m 4 --screen-name eDP # play four media at once on specific screen
        library {action} -m 4 --loop --crop     # play four cropped videos on a loop
        library {action} -m 4 --hstack          # use hstack style
"""


watch = play("watch")


redditadd = """library redditadd [--lookback N_DAYS] [--praw-site bot1] [database] paths ...

    Fetch data for redditors and reddits:

        library redditadd https://old.reddit.com/r/coolgithubprojects/ https://old.reddit.com/user/Diastro

    If you have a file with a list of subreddits you can do this:

        library redditadd --subreddits --db 96_Weird_History.db (cat ~/mc/96_Weird_History-reddit.txt)

    Likewise for redditors:

        library redditadd --redditors --db idk.db (cat ~/mc/shadow_banned.txt)
"""

redditupdate = """library redditupdate [--audio | --video] [-c CATEGORY] [--lookback N_DAYS] [--praw-site bot1] [database]

    Fetch the latest posts for every subreddit/redditor saved in your database

        library redditupdate edu_subreddits.db
"""

search = """library search

    Search text databases and subtitles

    $ library search fts.db boil
        7 captions
        /mnt/d/70_Now_Watching/DidubeTheLastStop-720p.mp4
           33:46 I brought a real stainless steel boiler
           33:59 The world is using only stainless boilers nowadays
           34:02 The boiler is old and authentic
           34:30 - This boiler? - Yes
           34:44 I am not forcing you to buy this boiler…
           34:52 Who will give her a one liter stainless steel boiler for one Lari?
           34:54 Glass boilers cost two

    Search and open file
    $ library search fts.db dashi --open
"""

history = """library history [--frequency daily weekly (monthly) yearly] [--limit LIMIT] DATABASE [(all) watching watched created modified deleted]

    Explore history through different facets

    $ library history video.db watched
    Finished watching:
    ╒═══════════════╤═════════════════════════════════╤════════════════╤════════════╤════════════╕
    │ time_period   │ duration_sum                    │ duration_avg   │ size_sum   │ size_avg   │
    ╞═══════════════╪═════════════════════════════════╪════════════════╪════════════╪════════════╡
    │ 2022-11       │ 4 days, 16 hours and 20 minutes │ 55.23 minutes  │ 26.3 GB    │ 215.9 MB   │
    ├───────────────┼─────────────────────────────────┼────────────────┼────────────┼────────────┤
    │ 2022-12       │ 23 hours and 20.03 minutes      │ 35.88 minutes  │ 8.3 GB     │ 213.8 MB   │
    ├───────────────┼─────────────────────────────────┼────────────────┼────────────┼────────────┤
    │ 2023-01       │ 17 hours and 3.32 minutes       │ 15.27 minutes  │ 14.3 GB    │ 214.1 MB   │
    ├───────────────┼─────────────────────────────────┼────────────────┼────────────┼────────────┤
    │ 2023-02       │ 4 days, 5 hours and 60 minutes  │ 23.17 minutes  │ 148.3 GB   │ 561.6 MB   │
    ├───────────────┼─────────────────────────────────┼────────────────┼────────────┼────────────┤
    │ 2023-03       │ 2 days, 18 hours and 18 minutes │ 11.20 minutes  │ 118.1 GB   │ 332.8 MB   │
    ├───────────────┼─────────────────────────────────┼────────────────┼────────────┼────────────┤
    │ 2023-05       │ 5 days, 5 hours and 4 minutes   │ 45.75 minutes  │ 152.9 GB   │ 932.1 MB   │
    ╘═══════════════╧═════════════════════════════════╧════════════════╧════════════╧════════════╛

    $ library history video.db created --frequency yearly
    Created media:
    ╒═══════════════╤════════════════════════════════════════════╤════════════════╤════════════╤════════════╕
    │   time_period │ duration_sum                               │ duration_avg   │ size_sum   │ size_avg   │
    ╞═══════════════╪════════════════════════════════════════════╪════════════════╪════════════╪════════════╡
    │          2005 │ 9.78 minutes                               │ 1.95 minutes   │ 16.9 MB    │ 3.4 MB     │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2006 │ 7 hours and 10.67 minutes                  │ 5 minutes      │ 891.1 MB   │ 10.4 MB    │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2007 │ 1 day, 17 hours and 33 minutes             │ 8.55 minutes   │ 5.9 GB     │ 20.3 MB    │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2008 │ 5 days, 16 hours and 10 minutes            │ 17.02 minutes  │ 20.7 GB    │ 43.1 MB    │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2009 │ 24 days, 2 hours and 56 minutes            │ 33.68 minutes  │ 108.4 GB   │ 105.2 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2010 │ 1 month, 1 days and 1 minutes              │ 35.52 minutes  │ 124.2 GB   │ 95.7 MB    │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2011 │ 2 months, 14 days, 1 hour and 22 minutes   │ 55.93 minutes  │ 222.0 GB   │ 114.9 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2012 │ 2 months, 22 days, 19 hours and 17 minutes │ 45.50 minutes  │ 343.6 GB   │ 129.6 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2013 │ 3 months, 11 days, 21 hours and 48 minutes │ 42.72 minutes  │ 461.1 GB   │ 131.7 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2014 │ 3 months, 7 days, 10 hours and 22 minutes  │ 46.80 minutes  │ 529.6 GB   │ 173.1 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2015 │ 2 months, 21 days, 23 hours and 36 minutes │ 36.73 minutes  │ 452.7 GB   │ 139.2 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2016 │ 3 months, 26 days, 7 hours and 59 minutes  │ 39.48 minutes  │ 603.4 GB   │ 139.9 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2017 │ 3 months, 10 days, 2 hours and 19 minutes  │ 31.78 minutes  │ 543.5 GB   │ 117.5 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2018 │ 3 months, 21 days, 20 hours and 56 minutes │ 30.98 minutes  │ 607.5 GB   │ 114.8 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2019 │ 5 months, 23 days, 2 hours and 30 minutes  │ 35.77 minutes  │ 919.7 GB   │ 129.7 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2020 │ 7 months, 16 days, 10 hours and 58 minutes │ 26.15 minutes  │ 1.2 TB     │ 93.9 MB    │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2021 │ 7 months, 21 days, 9 hours and 40 minutes  │ 39.93 minutes  │ 1.3 TB     │ 149.9 MB   │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2022 │ 17 years, 3 months, 0 days and 21 hours    │ 19.62 minutes  │ 35.8 TB    │ 77.5 MB    │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │          2023 │ 15 years, 3 months, 24 days and 1 hours    │ 17.57 minutes  │ 27.6 TB    │ 60.2 MB    │
    ╘═══════════════╧════════════════════════════════════════════╧════════════════╧════════════╧════════════╛
    ╒════════════════════════════════════════════════════════════════════════════════════════════╤═══════════════╤════════════════╕
    │ title_path                                                                                 │ duration      │ time_created   │
    ╞════════════════════════════════════════════════════════════════════════════════════════════╪═══════════════╪════════════════╡
    │ [Eng Sub] TVB Drama | The King Of Snooker 桌球天王 07/20 | Adam Cheng | 2009 #Chinesedrama │ 43.85 minutes │ yesterday      │
    │ https://www.youtube.com/watch?v=zntYD1yLrG8                                                │               │                │
    ├────────────────────────────────────────────────────────────────────────────────────────────┼───────────────┼────────────────┤
    │ [Eng Sub] TVB Drama | The King Of Snooker 桌球天王 08/20 | Adam Cheng | 2009 #Chinesedrama │ 43.63 minutes │ yesterday      │
    │ https://www.youtube.com/watch?v=zQnSfoWrh-4                                                │               │                │
    ├────────────────────────────────────────────────────────────────────────────────────────────┼───────────────┼────────────────┤
    │ [Eng Sub] TVB Drama | The King Of Snooker 桌球天王 06/20 | Adam Cheng | 2009 #Chinesedrama │ 43.60 minutes │ yesterday      │
    │ https://www.youtube.com/watch?v=Qiax1kFyGWU                                                │               │                │
    ├────────────────────────────────────────────────────────────────────────────────────────────┼───────────────┼────────────────┤
    │ [Eng Sub] TVB Drama | The King Of Snooker 桌球天王 04/20 | Adam Cheng | 2009 #Chinesedrama │ 43.45 minutes │ yesterday      │
    │ https://www.youtube.com/watch?v=NT9C3PRrlTA                                                │               │                │
    ├────────────────────────────────────────────────────────────────────────────────────────────┼───────────────┼────────────────┤
    │ [Eng Sub] TVB Drama | The King Of Snooker 桌球天王 02/20 | Adam Cheng | 2009 #Chinesedrama │ 43.63 minutes │ yesterday      │
    │ https://www.youtube.com/watch?v=MjpCiTawlTE                                                │               │                │
    ╘════════════════════════════════════════════════════════════════════════════════════════════╧═══════════════╧════════════════╛

    $ library history video.db deleted
    Deleted media:
    ╒═══════════════╤════════════════════════════════════════════╤════════════════╤════════════╤════════════╕
    │ time_period   │ duration_sum                               │ duration_avg   │ size_sum   │ size_avg   │
    ╞═══════════════╪════════════════════════════════════════════╪════════════════╪════════════╪════════════╡
    │ 2023-04       │ 1 year, 10 months, 3 days and 8 hours      │ 4.47 minutes   │ 1.6 TB     │ 7.4 MB     │
    ├───────────────┼────────────────────────────────────────────┼────────────────┼────────────┼────────────┤
    │ 2023-05       │ 9 months, 26 days, 20 hours and 34 minutes │ 30.35 minutes  │ 1.1 TB     │ 73.7 MB    │
    ╘═══════════════╧════════════════════════════════════════════╧════════════════╧════════════╧════════════╛
    ╒════════════════════════════════════════════════════════════════════════════════════════════════════════════╤═══════════════╤══════════════════╤════════════════╕
    │ title_path                                                                                                 │ duration      │   subtitle_count │ time_deleted   │
    ╞════════════════════════════════════════════════════════════════════════════════════════════════════════════╪═══════════════╪══════════════════╪════════════════╡
    │ Terminus (1987)                                                                                            │ 1 hour and    │                0 │ yesterday      │
    │ /mnt/d/70_Now_Watching/Terminus_1987.mp4                                                                   │ 15.55 minutes │                  │                │
    ├────────────────────────────────────────────────────────────────────────────────────────────────────────────┼───────────────┼──────────────────┼────────────────┤
    │ Commodore 64 Longplay [062] The Transformers (EU) /mnt/d/71_Mealtime_Videos/Youtube/World_of_Longplays/Com │ 24.77 minutes │                2 │ yesterday      │
    │ modore_64_Longplay_062_The_Transformers_EU_[1RRX7Kykb38].webm                                              │               │                  │                │
    ...

"""

playlists = """library playlists [database] [--aggregate] [--fields] [--json] [--delete ...]

    List of Playlists

        library playlists
        ╒══════════╤════════════════════╤══════════════════════════════════════════════════════════════════════════╕
        │ ie_key   │ title              │ path                                                                     │
        ╞══════════╪════════════════════╪══════════════════════════════════════════════════════════════════════════╡
        │ Youtube  │ Highlights of Life │ https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n │
        ╘══════════╧════════════════════╧══════════════════════════════════════════════════════════════════════════╛

    Aggregate Report of Videos in each Playlist

        library playlists -p a
        ╒══════════╤════════════════════╤══════════════════════════════════════════════════════════════════════════╤═══════════════╤═════════╕
        │ ie_key   │ title              │ path                                                                     │ duration      │   count │
        ╞══════════╪════════════════════╪══════════════════════════════════════════════════════════════════════════╪═══════════════╪═════════╡
        │ Youtube  │ Highlights of Life │ https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n │ 53.28 minutes │      15 │
        ╘══════════╧════════════════════╧══════════════════════════════════════════════════════════════════════════╧═══════════════╧═════════╛
        1 playlist
        Total duration: 53.28 minutes

    Print only playlist urls:
        Useful for piping to other utilities like xargs or GNU Parallel.
        library playlists -p f
        https://www.youtube.com/playlist?list=PL7gXS9DcOm5-O0Fc1z79M72BsrHByda3n

    Remove a playlist/channel and all linked videos:
        library playlists --remove https://vimeo.com/canal180

"""

download_status = """library download-status [database]

    Print download queue groups

        library download-status video.db
        ╒═════════════════════╤═════════════╤══════════════════╤════════════════════╤══════════╕
        │ category            │ ie_key      │ duration         │   never_downloaded │   errors │
        ╞═════════════════════╪═════════════╪══════════════════╪════════════════════╪══════════╡
        │ 71_Mealtime_Videos  │ Youtube     │ 3 hours and 2.07 │                 76 │        0 │
        │                     │             │ minutes          │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ 75_MovieQueue       │ Dailymotion │                  │                 53 │        0 │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ 75_MovieQueue       │ Youtube     │ 1 day, 18 hours  │                 30 │        0 │
        │                     │             │ and 6 minutes    │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Dailymotion         │ Dailymotion │                  │                186 │      198 │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Uncategorized       │ Youtube     │ 1 hour and 52.18 │                  1 │        0 │
        │                     │             │ minutes          │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Vimeo               │ Vimeo       │                  │                253 │       49 │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Youtube             │ Youtube     │ 2 years, 4       │              51676 │      197 │
        │                     │             │ months, 15 days  │                    │          │
        │                     │             │ and 6 hours      │                    │          │
        ├─────────────────────┼─────────────┼──────────────────┼────────────────────┼──────────┤
        │ Playlist-less media │ Youtube     │ 4 months, 23     │               2686 │        7 │
        │                     │             │ days, 19 hours   │                    │          │
        │                     │             │ and 33 minutes   │                    │          │
        ╘═════════════════════╧═════════════╧══════════════════╧════════════════════╧══════════╛

    Simulate --safe flag

        library download-status video.db --safe

    Show only download attempts with errors

        library download-status video.db --errors
"""

tabs = """library tabs DATABASE

    Tabs is meant to run **once per day**. Here is how you would configure it with `crontab`:

        45 9 * * * DISPLAY=:0 library tabs /home/my/tabs.db

    If things aren't working you can use `at` to simulate a similar environment as `cron`

        echo 'fish -c "export DISPLAY=:0 && library tabs /full/path/to/tabs.db"' | at NOW

    You can also invoke tabs manually:

        library tabs -L 1  # open one tab

    Print URLs

        library tabs -w "frequency='yearly'" -p
        ╒════════════════════════════════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                                           │ frequency   │ time_valid   │
        ╞════════════════════════════════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/Autonomia/top/?sort=top&t=year        │ yearly      │ Dec 31 1970  │
        ├────────────────────────────────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/top/?sort=top&t=year        │ yearly      │ Dec 31 1970  │
        ├────────────────────────────────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/ExperiencedDevs/top/?sort=top&t=year  │ yearly      │ Dec 31 1970  │

        ...

        ╘════════════════════════════════════════════════════════════════╧═════════════╧══════════════╛

    View how many yearly tabs you have:

        library tabs -w "frequency='yearly'" -p a
        ╒═══════════╤═════════╕
        │ path      │   count │
        ╞═══════════╪═════════╡
        │ Aggregate │     134 │
        ╘═══════════╧═════════╛

    Delete URLs

        library tb -p -s cyber
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
        library tb -p -w "path='https://www.reddit.com/r/cyberDeck/'" --delete
        Removed 1 metadata records
        library tb -p -s cyber
        ╒═══════════════════════════════════════╤═════════════╤══════════════╕
        │ path                                  │ frequency   │ time_valid   │
        ╞═══════════════════════════════════════╪═════════════╪══════════════╡
        │ https://old.reddit.com/r/cyberDeck/to │ yearly      │ Dec 31 1970  │
        │ p/?sort=top&t=year                    │             │              │
        ├───────────────────────────────────────┼─────────────┼──────────────┤
        │ https://old.reddit.com/r/Cyberpunk/to │ yearly      │ Aug 29 2023  │
        │ p/?sort=top&t=year                    │             │              │
        ╘═══════════════════════════════════════╧═════════════╧══════════════╛
"""

tabsadd = r"""library tabsadd [--frequency daily weekly (monthly) quarterly yearly] [--category CATEGORY] [--no-sanitize] DATABASE URLS ...

    Adding one URL:

        library tabsadd -f monthly -c travel ~/lb/tabs.db https://old.reddit.com/r/Colombia/top/?sort=top&t=month

        Depending on your shell you may need to escape the URL (add quotes)

        If you use Fish shell know that you can enable features to make pasting easier:
            set -U fish_features stderr-nocaret qmark-noglob regex-easyesc ampersand-nobg-in-token

        Also I recommend turning Ctrl+Backspace into a super-backspace for repeating similar commands with long args:
            echo 'bind \b backward-kill-bigword' >> ~/.config/fish/config.fish

    Importing from a line-delimitated file:

        library tabsadd -f yearly -c reddit ~/lb/tabs.db (cat ~/mc/yearly-subreddit.cron)

"""

tubeadd = r"""library tubeadd [--audio | --video] [-c CATEGORY] [database] playlists ...

    Create a dl database / add links to an existing database

        library tubeadd dl.db https://www.youdl.com/c/BranchEducation/videos

    Add links from a line-delimited file

        library tubeadd reddit.db --playlist-file ./my_yt_subscriptions.txt

    Add metadata to links already in a database table

        library tubeadd reddit.db --playlist-db media

    You can also include a category for file organization

        library tubeadd -c Mealtime dl.db (cat ~/.jobs/todo/71_Mealtime_Videos)

    Files will be saved to <download prefix>/<tubeadd category>/

        For example:
        library tubeadd -c Cool ...
        library download D:\'My Documents'\ ...
        Media will be downloaded to 'D:\My Documents\Cool\'

    Fetch extra metadata:

        By default tubeadd will quickly add media at the expense of less metadata.
        If you plan on using `library download` then it doesn't make sense to use `--extra`.
        Downloading will add the extra metadata automatically to the database.
        You can always fetch more metadata later via tubeupdate:
        library tubeupdate tw.db --extra
"""

tubeupdate = """library tubeupdate [--audio | --video] [-c CATEGORY] [database]

    Fetch the latest videos for every playlist saved in your database

        library tubeupdate educational.db

    Or limit to specific categories...

        library tubeupdate -c "Bob Ross" educational.db

    Run with --optimize to add indexes (might speed up searching but the size will increase):

        library tubeupdate --optimize examples/music.tl.db

    Fetch extra metadata:

        By default tubeupdate will quickly add media.
        You can run with --extra to fetch more details: (best resolution width, height, subtitle tags, etc)

        library tubeupdate educational.db --extra https://www.youtube.com/channel/UCBsEUcR-ezAuxB2WlfeENvA/videos
"""

bigdirs = """library bigdirs DATABASE [--limit (4000)] [--depth (0)] [--sort-by "deleted" | "played"] [--size=+5MB]

    See what folders take up space

        library bigdirs video.db
        library bigdirs audio.db
        library bigdirs fs.db
"""

christen = """library christen DATABASE [--run]

    Rename files to be somewhat normalized

    Default mode is dry-run

        library christen fs.db

    To actually do stuff use the run flag

        library christen audio.db --run

    You can optionally replace all the spaces in your filenames with dots

        library christen --dot-space video.db
"""
cluster_sort = """library cluster-sort [input_path | stdin] [output_path | stdout]

    Group lines of text into sorted output
"""

copy_play_counts = """library copy-play-counts DEST_DB SOURCE_DB ... [--source-prefix x] [--target-prefix y]

    Copy play count information between databases

        library copy-play-counts audio.db phone.db --source-prefix /storage/6E7B-7DCE/d --target-prefix /mnt/d
"""
dedupe = """library [--audio | --id | --title | --filesystem] [--only-soft-delete] [--limit LIMIT] DATABASE

    Dedupe your files
"""

merge_dbs = """library merge-dbs DEST_DB SOURCE_DB ... [--only-target-columns] [--only-new-rows] [--upsert] [--pk PK ...] [--table TABLE ...]

    Merge-DBs will insert new rows from source dbs to target db, table by table. If primary key(s) are provided,
    and there is an existing row with the same PK, the default action is to delete the existing row and insert the new row
    replacing all existing fields.

    Upsert mode will update matching PK rows such that if a source row has a NULL field and
    the destination row has a value then the value will be preserved instead of changed to the source row's NULL value.

    Ignore mode (--only-new-rows) will insert only rows which don't already exist in the destination db

    Test first by using temp databases as the destination db.
    Try out different modes / flags until you are satisfied with the behavior of the program

        library merge-dbs --pk path (mktemp --suffix .db) tv.db movies.db

    Merge database data and tables

        library merge-dbs --upsert --pk path video.db tv.db movies.db
        library merge-dbs --only-target-columns --only-new-rows --table media,playlists --pk path audio-fts.db audio.db

        library merge-dbs --pk id --only-tables subreddits reddit/81_New_Music.db audio.db
        library merge-dbs --only-new-rows --pk playlist_path,path --only-tables reddit_posts reddit/81_New_Music.db audio.db -v
"""

merge_online_local = """library merge-online-local DATABASE

    If you have previously downloaded YouTube or other online media, you can dedupe
    your database and combine the online and local media records as long as your
    files have the youtube-dl / yt-dlp id in the filename.
"""

optimize = """library optimize DATABASE [--force]

    Optimize library databases

    The force flag is usually unnecessary and it can take much longer
"""

redownload = """library redownload DATABASE

    If you have previously downloaded YouTube or other online media, but your
    hard drive failed or you accidentally deleted something, and if that media
    is still accessible from the same URL, this script can help to redownload
    everything that was scanned-as-deleted between two timestamps.

    List deletions:

        $ library redownload news.db
        Deletions:
        ╒═════════════════════╤═════════╕
        │ time_deleted        │   count │
        ╞═════════════════════╪═════════╡
        │ 2023-01-26T00:31:26 │     120 │
        ├─────────────────────┼─────────┤
        │ 2023-01-26T19:54:42 │      18 │
        ├─────────────────────┼─────────┤
        │ 2023-01-26T20:45:24 │      26 │
        ╘═════════════════════╧═════════╛
        Showing most recent 3 deletions. Use -l to change this limit

    Mark videos as candidates for download via specific deletion timestamp:

        $ library redownload city.db 2023-01-26T19:54:42
        ╒══════════╤════════════════╤═════════════════╤═══════════════════╤═════════╤══════════╤═══════╤══════════════════╤════════════════════════════════════════════════════════════════════════════════════════════════════════╕
        │ size     │ time_created   │ time_modified   │ time_downloaded   │   width │   height │   fps │ duration         │ path                                                                                                   │
        ╞══════════╪════════════════╪═════════════════╪═══════════════════╪═════════╪══════════╪═══════╪══════════════════╪════════════════════════════════════════════════════════════════════════════════════════════════════════╡
        │ 697.7 MB │ Apr 13 2022    │ Mar 11 2022     │ Oct 19            │    1920 │     1080 │    30 │ 21.22 minutes    │ /mnt/d/76_CityVideos/PRAIA DE BARRA DE JANGADA CANDEIAS JABOATÃO                                       │
        │          │                │                 │                   │         │          │       │                  │ RECIFE PE BRASIL AVENIDA BERNARDO VIEIRA DE MELO-4Lx3hheMPmg.mp4
        ...

    ...or between two timestamps inclusive:

        $ library redownload city.db 2023-01-26T19:54:42 2023-01-26T20:45:24
"""

relmv = """library relmv [--dry-run] SOURCE ... DEST

    Move files/folders without losing hierarchy metadata

    Move fresh music to your phone every Sunday:

        # move last weeks' music back to their source folders
        library relmv /mnt/d/80_Now_Listening/ /mnt/d/

        # move new music for this week
        library relmv (
            library listen ~/lb/audio.db --local-media-only --where 'play_count=0' --random -L 600 -p f
        ) /mnt/d/80_Now_Listening/
"""

scatter = """library scatter [--limit LIMIT] [--policy POLICY] [--sort SORT] --srcmounts SRCMOUNTS database relative_paths ...

    Balance size

        $ library scatter -m /mnt/d1:/mnt/d2:/mnt/d3:/mnt/d4/:/mnt/d5:/mnt/d6:/mnt/d7 ~/lb/fs/scatter.db subfolder/of/mergerfs/mnt
        Current path distribution:
        ╒═════════╤══════════════╤══════════════╤═══════════════╤════════════════╤═════════════════╤════════════════╕
        │ mount   │   file_count │ total_size   │ median_size   │ time_created   │ time_modified   │ time_scanned   │
        ╞═════════╪══════════════╪══════════════╪═══════════════╪════════════════╪═════════════════╪════════════════╡
        │ /mnt/d1 │        12793 │ 169.5 GB     │ 4.5 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d2 │        13226 │ 177.9 GB     │ 4.7 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d3 │            1 │ 717.6 kB     │ 717.6 kB      │ Jan 31         │ Jul 18 2022     │ yesterday      │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d4 │           82 │ 1.5 GB       │ 12.5 MB       │ Jan 31         │ Apr 22 2022     │ yesterday      │
        ╘═════════╧══════════════╧══════════════╧═══════════════╧════════════════╧═════════════════╧════════════════╛

        Simulated path distribution:
        5845 files should be moved
        20257 files should not be moved
        ╒═════════╤══════════════╤══════════════╤═══════════════╤════════════════╤═════════════════╤════════════════╕
        │ mount   │   file_count │ total_size   │ median_size   │ time_created   │ time_modified   │ time_scanned   │
        ╞═════════╪══════════════╪══════════════╪═══════════════╪════════════════╪═════════════════╪════════════════╡
        │ /mnt/d1 │         9989 │ 46.0 GB      │ 2.4 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d2 │        10185 │ 46.0 GB      │ 2.4 MB        │ Jan 27         │ Jul 19 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d3 │         1186 │ 53.6 GB      │ 30.8 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d4 │         1216 │ 49.5 GB      │ 29.5 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d5 │         1146 │ 53.0 GB      │ 30.9 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d6 │         1198 │ 48.8 GB      │ 30.6 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ├─────────┼──────────────┼──────────────┼───────────────┼────────────────┼─────────────────┼────────────────┤
        │ /mnt/d7 │         1182 │ 52.0 GB      │ 30.9 MB       │ Jan 27         │ Apr 07 2022     │ Jan 31         │
        ╘═════════╧══════════════╧══════════════╧═══════════════╧════════════════╧═════════════════╧════════════════╛
        ### Move 1182 files to /mnt/d7 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmpmr1628ij / /mnt/d7
        ### Move 1198 files to /mnt/d6 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmp9yd75f6j / /mnt/d6
        ### Move 1146 files to /mnt/d5 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmpfrj141jj / /mnt/d5
        ### Move 1185 files to /mnt/d3 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmpqh2euc8n / /mnt/d3
        ### Move 1134 files to /mnt/d4 with this command: ###
        rsync -aE --xattrs --info=progress2 --remove-source-files --files-from=/tmp/tmphzb0gj92 / /mnt/d4

    Balance device inodes for specific subfolder

        $ library scatter -m /mnt/d1:/mnt/d2 ~/lb/fs/scatter.db subfolder --group count --sort 'size desc'

    Scatter the most recent 100 files

        $ library scatter -m /mnt/d1:/mnt/d2 -l 100 -s 'time_modified desc' ~/lb/fs/scatter.db /

    Scatter without mountpoints (limited functionality; only good for balancing fs inodes)

        $ library scatter scatter.db /test/{0,1,2,3,4,5,6,7,8,9}
"""
surf = """library surf [--count COUNT] [--target-hosts TARGET_HOSTS] < stdin

    Streaming tab loader: press ctrl+c to stop.

    Open tabs from a line-delimited file:

        cat tabs.txt | library surf -n 5

    You will likely want to use this setting in `about:config`

        browser.tabs.loadDivertedInBackground = True

    If you prefer GUI, check out https://unli.xyz/tabsender/
"""

pushshift = """library pushshift [database] < stdin

    Download data (about 600GB jsonl.zst; 6TB uncompressed)

        wget -e robots=off -r -k -A zst https://files.pushshift.io/reddit/submissions/

    Load data from files via unzstd

        unzstd --memory=2048MB --stdout RS_2005-07.zst | library pushshift pushshift.db

    Or multiple (output is about 1.5TB SQLITE fts-searchable):

        for f in psaw/files.pushshift.io/reddit/submissions/*.zst
            echo "unzstd --memory=2048MB --stdout $f | library pushshift (basename $f).db"
            library optimize (basename $f).db
        end | parallel -j5
"""

reddit_selftext = """library reddit-selftext DATABASE

    Extract URLs from reddit selftext from the reddit_posts table to the media table
"""
