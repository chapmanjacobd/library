## lb: opinionated media library

Requires ffmpeg

### Install

```
pip install xklb
```

### Step 1. Extract Metadata

    lb-extract tv.db ./video/folder/

    lb-extract --audio podcasts.db ./your/music/or/podcasts/folder/

### Step 2. Watch / Listen

    wt --delete tv.db  # delete file after viewing

    lt --action=ask podcasts.db  # ask to delete or not after each file

### Repeat!

Implementing repeat / auto-play is left to the end user. I recommend something like this if you use fish shell:

```fish
function repeat
    while $argv
        and :
    end
end

repeat lt audio.db
```

or

```fish
function repeatn --description 'repeatn <count> <command>'
    for i in (seq 1 $argv[1])
        eval $argv[2..-1]
    end
end

repeat 5 lt audio.db
```

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
