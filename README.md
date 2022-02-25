# lb: media library

Requires ffmpeg

## Step 1. Extract Metadata

```
python -m extract -h

usage: extract.py [-h] [-ns] [-yt] [-sl] [-v] db [paths ...]

positional arguments:
  db
  paths

options:
  -h, --help            show this help message and exit
  -ns, --no-sub
  -yt, --youtube-only
  -sl, --subliminal-only
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

usage: watch.py [-h] [-keep] [-cast] [-cast-to CHROMECAST_DEVICE] [-s SEARCH] [-S SKIP] [-d DURATION] [-dm MIN_DURATION] [-dM MAX_DURATION] [-sz SIZE] [-szm MIN_SIZE] [-szM MAX_SIZE] [-mv MOVE]
                [-1] [-O] [-r] [-v]
                db

positional arguments:
  db

options:
  -h, --help            show this help message and exit
  -keep, --keep
  -cast, --chromecast
  -cast-to CHROMECAST_DEVICE, --chromecast-device CHROMECAST_DEVICE
  -s SEARCH, --search SEARCH
  -S SKIP, --skip SKIP
  -d DURATION, --duration DURATION
  -dm MIN_DURATION, --min-duration MIN_DURATION
  -dM MAX_DURATION, --max-duration MAX_DURATION
  -sz SIZE, --size SIZE
  -szm MIN_SIZE, --min-size MIN_SIZE
  -szM MAX_SIZE, --max-size MAX_SIZE
  -mv MOVE, --move MOVE
  -1, --last
  -O, --play-in-order
  -r, --random
  -v, --verbose
```

## Originally written to answer this question:

```
SELECT sum(duration)/60/60 as video_hours
FROM videos v
```

but you could also use it to catalog footage (ie. if you are a DIT, extract TIMECODE), although I'm sure there are better tools.
