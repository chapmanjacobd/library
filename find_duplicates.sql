select * from media mp3, media ogg
where mp3.format_name !='ogg' and ogg.format_name = 'ogg'
and cast(mp3.duration as int) >= cast(ogg.duration as int) - 2
and cast(mp3.duration as int) <= cast(ogg.duration as int) + 2
and replace(replace(replace(replace(replace(mp3.filename,' ',''), '-', ''),'_',''),'[',''),']','') = 
    replace(replace(replace(replace(replace(ogg.filename,' ',''), '-', ''),'_',''),'[',''),']','')
limit 5
;