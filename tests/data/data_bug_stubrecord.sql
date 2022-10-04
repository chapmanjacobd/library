select
        *
    from media
    left join (SELECT
        *
    FROM playlists
    WHERE 1=1
        and time_deleted=0
        and (category is null or category != '__BLOCKLIST_ENTRY_')
) p on p.ie_key != 'Local' and p.path = media.playlist_path
where 1=1
    and media.time_downloaded=0
    and media.time_deleted=0
;

select
DISTINCT playlist_path
from media
left join (SELECT
    *
FROM playlists
WHERE 1=1
    and time_deleted=0
    and (category is null or category != '__BLOCKLIST_ENTRY_')
) p on (p.ie_key = 'Local' and media.path like p.path || '%' ) or (p.ie_key != 'Local' and p.path = media.playlist_path)
where 1=1
    and media.time_downloaded=0
    and media.time_deleted=0
    AND p.ie_key IS NULL
;

UPDATE playlists SET time_deleted = 0 WHERE time_deleted IS null;
