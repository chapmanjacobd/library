## lb: opinionated media library

Requires ffmpeg

### Install

```
pip install xklb
```

### Quick Start

#### Step 1. Extract Metadata

    lb extract tv.db ./video/folder/

    lb extract --audio podcasts.db ./your/music/or/podcasts/folder/

#### Step 2. Watch / Listen

    wt tv.db  # the default post-action is to do nothing after viewing

    wt --post-action delete tv.db  # delete file after viewing

    lt --post-action=ask podcasts.db  # ask to delete or not after each file


### Repeat!

    lt -u random         # listen to ONE random song
    lt --repeat 5        # listen to FIVE songs
    lt -l inf            # listen to songs indefinitely
    lt -s infinite       # listen to songs from the band infinite

If that's confusing you could always use your shell:

```fish
function repeat
    while $argv
        and :
    end
end

repeat lt -s finite  # listen to finite songs infinitely
```

### Example Usage


#### Watch longest videos

    wt tv.db --sort duration desc

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

### Advanced Features

If you want to specify more than one directory you will need to make the db file explicit:

    $ lb extract --filesystem fs.db one/ two/


### Searching filesystem

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
