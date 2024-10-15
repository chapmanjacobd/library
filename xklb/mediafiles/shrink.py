# group by exts
# show current size and estimated size
# total estimated savings

# numfmt --to=iec (sqlite-utils --no-headers --raw-lines ~/lb/video.db "select sum(size)-sum(duration*100000) from media where time_deleted=0 and video_count>=1 and video_codecs != 'av1' and size/duration > 100000")
# numfmt --to=iec (sqlite-utils --no-headers --raw-lines ~/lb/audio.db "select sum(size)-sum(duration*18000) from media where time_deleted=0 and video_count=0 and audio_count>=1 and audio_codecs != 'opus' and size/duration > 18000")

'''
    try:
        query, bindings = sqlgroups.media_sql(args)
    except sqlite3.OperationalError:
        query, bindings = sqlgroups.fs_sql(args, args.limit)
'''
