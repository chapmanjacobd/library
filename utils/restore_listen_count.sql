attach '/home/xk/lb/audio.db' AS audio;
attach '/home/xk/lb/audio.db.bak' AS audiobak;
UPDATE
    audio.media SET listen_count = (
        SELECT
            listen_count
        FROM
            audiobak.media
        WHERE
            audio.media.filename = audiobak.media.filename
    )
WHERE
    EXISTS(
        SELECT
            1
        FROM
            audiobak.media
        WHERE
            audio.media.filename = audiobak.media.filename
            AND audiobak.media.listen_count > 0
    );
