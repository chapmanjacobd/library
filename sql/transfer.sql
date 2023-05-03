select group_concat(name) from PRAGMA_TABLE_INFO('playlists');
INSERT into playlists select time_deleted,path,ie_key,category,title,uploader,id,dl_config from ftsdb.playlists where path not in (select path from playlists);

select group_concat(name) from PRAGMA_TABLE_INFO('media');
INSERT into media select play_count,time_played,size,time_created,time_modified,time_downloaded,time_deleted,video_count,audio_count,chapter_count,width,height,fps,duration,subtitle_count,attachment_count,path,ie_key,sparseness,language,id,title,view_count,uploader,playlist_path from ftsdb.media where path not in (select path from media);
