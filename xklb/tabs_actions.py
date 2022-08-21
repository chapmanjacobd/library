from xklb.fs_actions import parse_args, process_actions
from xklb.utils import SC
from xklb.utils_player import generic_player


def tabs():
    args = parse_args(SC.tabs, "tabs.db")
    args.player = generic_player(args)
    args.delay = 0.1
    process_actions(args)


"""
open browser
print

by frequency (math.min(args.limit, freq_limit))
by number -L

import pandas as pd
quarter = pd.Timestamp(dt.date(2016, 2, 29)).quarter

(x.month-1)//3 +1 quarter

people can read ahead and if they read everything then running tb won't do anything until the minimum time of the set frequency

example frequency that could be used:

    -q daily
    -q weekly (spaced evenly throughout the week if less than 7 links in the category)
    -q monthly (spaced evenly throughout the month if less than 30 links in the category)
    -q quarterly (spaced evenly throughout the month if less than 90 links in the category)
    -q yearly (spaced evenly throughout the year if less than 365 links in the category)

if 14 tabs, two URLs are opened per day of the week.

1 cron daily

categoryless mode: ignore categories when determining sequencing--only frequency is used

cron is responsible for running python. `lb tabs` is merely a way to organize tabs into different categories--but you could easily do this with files as well.


order by play_count
, ROW_NUMBER() OVER ( PARTITION BY category ) -- prefer to spread categories over time
, random()

divmod(15, 7)

function tabs-monthly
    set day_of_week (date "+%w" + 1)
    set day_of_month (date "+%d")
    set day_of_year (date "+%j")

    set temp_file (mktemp)
    cat ~/mc/monthly.cron ~/mc/30_Computing-reddit.monthly.cron >$temp_file
    set file_len (cat $temp_file | count)
    while test $day_of_month -lt $file_len
        echo $day_of_month
        set url (sed "$day_of_month""q;d" $temp_file)
        open $url

        set day_of_month (math "$day_of_month + 30")
    end


    set file ~/mc/30_Computing-reddit.yearly.cron
    set file_len (wc -l < $file)

    if test $day_of_year -gt $file_len
        open (shuf -n1 "$file")
    end

    while test $day_of_year -lt $file_len
        echo $day_of_year
        set url (sed "$day_of_year""q;d" $file)
        open $url

        set day_of_year (math "$day_of_year + 365")
    end

end


"""
