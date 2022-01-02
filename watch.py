import sqlite3
from datetime import datetime
from glob import glob
from shlex import quote

import pandas as pd
from joblib import Parallel, delayed
from rich import inspect, print

from db import con
from utils import cmd

next_video = dict(con.execute("""
SELECT filename, duration / filesize AS seconds_per_byte,
CASE
    WHEN filesize < 1024 THEN filesize || 'B'
    WHEN filesize >=  1024 AND filesize < (1024 * 1024) THEN (filesize / 1024) || 'KB'
    WHEN filesize >= (1024 * 1024)  AND filesize < (1024 * 1024 * 1024) THEN (filesize / (1024 * 1024)) || 'MB'
    WHEN filesize >= (1024 * 1024 * 1024) AND filesize < (1024 * 1024 * 1024 *1024) THEN (filesize / (1024 * 1024 * 1024)) || 'GB'
    WHEN filesize >= (1024 * 1024 * 1024 * 1024) THEN (filesize / (1024 * 1024 * 1024 * 1024)) || 'TB'
END AS filesize
FROM videos2
WHERE duration IS NOT NULL
ORDER BY 2 ASC
limit 1
""").fetchone())['filename']

print(next_video)
cmd(f"mpv --quiet {quote(next_video)} --fs")
cmd(f"trash-put {quote(next_video)}")
con.execute("delete from videos2 where filename = ?",(next_video,))
con.commit()
