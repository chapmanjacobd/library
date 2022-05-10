# lb: media library

Requires ffmpeg

## Step 1. Extract Metadata

```
python -m extract -h

usage: extract.py [-h] [-a] [-s] [-yt] [-sl] [-f] [-v] db [paths ...]

positional arguments:
  db
  paths

options:
  -h, --help            show this help message and exit
  -a, --audio
  -s, --subtitle
  -yt, --youtube-only
  -sl, --subliminal-only
  -f, --force-rescan
  -v, --verbose
```

## Step 2. Watch

### Watch largest video first

```sh
python -m watch ./videos.db
```

### Watch specific video series in order

```sh
python -m watch ./videos.db --search 'title of series' --play-in-order
```

### Watch Options

```sh
python -m watch -h

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
```

### Listen Options

```sh
python -m listen -h

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
```

## Originally written to answer this question:

```
SELECT sum(duration)/60/60 as video_hours
FROM media v
```

but you could also use it to catalog footage (ie. if you are a DIT, extract TIMECODE), although I'm sure there are better tools.
