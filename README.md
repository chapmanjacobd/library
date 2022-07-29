## lb: opinionated media library

Requires ffmpeg, mpv

### Install

```
pip install xklb
```

### Step 1. Extract Metadata

    lb-extract tv.db ./video/folder/

    lb-extract --audio podcasts.db ./your/music/or/podcasts/folder/

### Step 2. Watch / Listen

    wt tv.db

    lt podcasts.db

#### Watch longest videos

    wt tv.db --sort 'duration desc'

#### Watch specific video series in order

    wt tv.db --search 'title of series' --play-in-order

#### There are multiple strictness levels of --play-in-order. If things aren't playing in order try adding more `O`s:

    wt tv.db --search 'title of series' -O    # default
    wt tv.db --search 'title of series' -OO   # slower, more complex algorithm
    wt tv.db --search 'title of series' -OOO  # most strict

#### I usually use the following:

    lt -cast -s '  ost'      # for listening to OSTs on my chromecast groups
    wt -u priority -w sub=0  # for exercising and watching YouTube
    wt -u duration --print -s 'video title'  # when I want to check if I've downloaded something before

#### Watch Options

    wt -h

    usage: watch.py [-h] [-1] [-cast-to CHROMECAST_DEVICE] [-cast] [-f] [-d DURATION]
                    [-dM MAX_DURATION] [-dm MIN_DURATION] [-keep] [-list] [-filename]
                    [-printquery] [-mv MOVE] [-O] [-r] [-s SEARCH] [-E EXCLUDE] [-S SKIP]
                    [-t TIME_LIMIT] [-v] [-vlc] [-z SIZE] [-zM MAX_SIZE] [-zm MIN_SIZE]
                    db

    positional arguments:
    db

    options:
    -h, --help            show this help message and exit
    -1, --last
    -cast-to CHROMECAST_DEVICE, --chromecast-device CHROMECAST_DEVICE
    -cast, --chromecast
    -f, --force-transcode
    -d DURATION, --duration DURATION
    -dM MAX_DURATION, --max-duration MAX_DURATION
    -dm MIN_DURATION, --min-duration MIN_DURATION
    -keep, --keep
    -list, --list
    -filename, --filename
    -printquery, --printquery
    -mv MOVE, --move MOVE
    -O, --play-in-order
    -r, --random
    -s SEARCH, --search SEARCH
    -E EXCLUDE, --exclude EXCLUDE
    -S SKIP, --skip SKIP
    -t TIME_LIMIT, --time-limit TIME_LIMIT
    -v, --verbose
    -vlc, --vlc
    -z SIZE, --size SIZE
    -zM MAX_SIZE, --max-size MAX_SIZE
    -zm MIN_SIZE, --min-size MIN_SIZE

#### Listen Options

    lt -h

    usage: listen.py [-h] [-cast] [-cast-to CHROMECAST_DEVICE] [-s SEARCH] [-E EXCLUDE]
                    [-S SKIP] [-d DURATION] [-dm MIN_DURATION] [-dM MAX_DURATION]
                    [-sz SIZE] [-szm MIN_SIZE] [-szM MAX_SIZE] [-mv MOVE] [-wl] [-O]
                    [-r] [-v]
                    db

    positional arguments:
    db

    options:
    -h, --help            show this help message and exit
    -cast, --chromecast
    -cast-to CHROMECAST_DEVICE, --chromecast-device CHROMECAST_DEVICE
    -s SEARCH, --search SEARCH
    -E EXCLUDE, --exclude EXCLUDE
    -S SKIP, --skip SKIP
    -d DURATION, --duration DURATION
    -dm MIN_DURATION, --min-duration MIN_DURATION
    -dM MAX_DURATION, --max-duration MAX_DURATION
    -sz SIZE, --size SIZE
    -szm MIN_SIZE, --min-size MIN_SIZE
    -szM MAX_SIZE, --max-size MAX_SIZE
    -mv MOVE, --move MOVE
    -wl, --with-local
    -O, --play-in-order
    -r, --random
    -v, --verbose
