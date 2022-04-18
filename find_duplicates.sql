select
mp3.filename,
mp3.filesize,
mp3.format_name,
mp3.duration,
ogg.filename,
ogg.filesize,
ogg.format_name,
ogg.duration
from media mp3, media ogg
where mp3.fid < ogg.fid
--and mp3.format_name !='ogg' and ogg.format_name = 'ogg'
and cast(mp3.duration as int) >= cast(ogg.duration as int) - 2
and cast(mp3.duration as int) <= cast(ogg.duration as int) + 2
and mp3.NUQ = ogg.NUQ and mp3.title = ogg.title and mp3.artist=ogg.artist and mp3.album=ogg.album
--limit 5