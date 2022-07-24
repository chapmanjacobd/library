attach 'audio.db' as audio;
attach 'audio.db.bak' as audiobak;
UPDATE audio.media
    set listen_count = b.listen_count
from audio.media a
    inner join
        audiobak.media b on b.filename = a.filename
    where b.listen_count > 0;
