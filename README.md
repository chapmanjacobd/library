# lb: opinionated media library

Requires `ffmpeg`

To quote an old wise philosopher: "[The future is [...] auto-tainment](https://www.youtube.com/watch?v=F9sZFrsjPp0)"

## Install

    pip install xklb

## Quick Start -- filesystem

### 1. Extract Metadata

    lb extract tv.db ./video/folder/
    OR
    lb extract ./tv/  # when not specified, db will be created as `video.db`
    OR
    lb extract --audio ./music/  # db will be created as `audio.db`

If you need to update the database -- run the same command again. Only the new files will be scanned.

### 2. Watch / Listen from local files

    wt tv.db                       # the default post-action is to do nothing after playing
    wt tv.db --post-action delete  # delete file after playing
    lt boring.db --post-action=ask # ask to delete after playing

## Quick Start -- virtual

### 1. Download Metadata

    lb tubeadd educational.db https://www.youtube.com/c/BranchEducation/videos

Download playlist and channel metadata. Break free of the YouTube algo~

    lb tubeadd maker.db https://www.youtube.com/c/CuriousMarc/videos https://www.youtube.com/c/element14presents/videos/ https://www.youtube.com/c/DIYPerks/videos

You can add more than one at a time.

    lb tubeadd maker.db https://vimeo.com/terburg

And you can always add more later--even from different websites.

    lb tubeadd maker.db !TEDx
    lb tubeadd maker.db --yt-dlp-config playlistend=1000

To prevent mistakes the default configuration is to download metadata for only the newest 20,000 videos per playlist/channel. Be aware that there are some YouTube Channels which have many--for example the TEDx channel has about 180,000 videos. Some channels even have upwards of two million videos. Probably more than you could watch in one sitting. On a high-speed connection (>500 Mbps), it can take up to five hours just to download the metadata for 180,000 videos. My advice: start with the 20,000.

#### 1a. Get new videos for saved playlists

    lb tubeupdate

Tubeupdate will go through all the added playlists and fetch metadata of any new videos.

### 2. Watch / Listen from websites

    lb tubewatch maker.db

## Organize using separate databases

    lb extract --audio both.db ./audiobooks/ ./podcasts/
    lb extract --audio audiobooks.db ./audiobooks/
    lb extract --audio podcasts.db ./podcasts/ ./another/more/secret/podcasts_folder/

## Example Usage

### Repeat

    lt -u random         # listen to ONE random song
    lt --limit 5        # listen to FIVE songs
    lt -l inf            # listen to songs indefinitely
    lt -s infinite       # listen to songs from the band infinite

If that's confusing (or if you are trying to load 4 billion files) you could always use your shell:

    function repeat
        while $argv
            and :
        end
    end

    repeat lt -s finite  # listen to finite songs infinitely

### Watch longest videos

    wt tv.db --sort duration desc

### Watch specific video series in order

    wt tv.db --search 'title of series' --play-in-order

### There are multiple strictness levels of --play-in-order. If things aren't playing in order try adding more `O`s

    wt tv.db --search 'title of series' -O    # default
    wt tv.db --search 'title of series' -OO   # slower, more complex algorithm
    wt tv.db --search 'title of series' -OOO  # most strict

### I usually use the following

    lt -cast -s '  ost'      # for listening to OSTs on my chromecast groups
    wt -u priority -w sub=0  # for exercising and watching YouTube
    wt -u duration --print -s 'video title'  # when I want to check if I've downloaded something before

## Advanced Features

### Extract

If you want to specify more than one directory you will need to make the db file explicit:

    lb extract --filesystem fs.db one/ two/

## Searching filesystem

You can also use `lb` for any files:

    $ lb extract -fs ~/d/41_8bit/

    $ lb fs fs.db -p a -s mario luigi
    ╒═══════════╤══════════════╤══════════╤═════════╕
    │ path      │   sparseness │ size     │   count │
    ╞═══════════╪══════════════╪══════════╪═════════╡
    │ Aggregate │            1 │ 215.0 MB │       7 │
    ╘═══════════╧══════════════╧══════════╧═════════╛

    $ lb fs -p -s mario -s luigi -s jpg -w is_dir=0 -u 'size desc'
    ╒═══════════════════════════════════════╤══════════════╤═════════╕
    │ path                                  │   sparseness │ size    │
    ╞═══════════════════════════════════════╪══════════════╪═════════╡
    │ /mnt/d/41_8bit/roms/gba/media/images/ │      1.05632 │ 58.2 kB │
    │ Mario & Luigi - Superstar Saga (USA,  │              │         │
    │ Australia).jpg                        │              │         │
    ├───────────────────────────────────────┼──────────────┼─────────┤
    │ /mnt/d/41_8bit/roms/gba/media/box3d/M │      1.01583 │ 44.4 kB │
    │ ario & Luigi - Superstar Saga (USA,   │              │         │
    │ Australia).jpg                        │              │         │
    ╘═══════════════════════════════════════╧══════════════╧═════════╛
