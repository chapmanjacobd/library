def combine(list_):
    if isinstance(list_, str):
        list_ = [list_]

    if list_ is None or len(list_) == 0:
        return None

    no_comma = sum([s.split(",") for s in list_], [])
    no_semicol = sum([s.split(";") for s in no_comma], [])
    no_unknown = [x for x in no_semicol if x.lower() not in ["unknown", ""]]
    return ";".join(no_unknown)


def safe_unpack(list_, idx=0):
    if list_ is None:
        return None
    try:
        return list_[idx]
    except IndexError:
        return None


def remove_known_tags(m):
    tags = m.as_dict()
    known_tags = [
        'encoder',
        'TMED',
        'TSO2',
        'artist-sort',
        'ASIN',
        'Acoustid Id',
        'Artists',
        'BARCODE',
        'CATALOGNUMBER',
        'MusicBrainz Album Artist Id',
        'MusicBrainz Album Id',
        'MusicBrainz Album Release Country',
        'musicbrainz album release country',
        'MusicBrainz Album Status',
        'MusicBrainz Album Type',
        'MusicBrainz Artist Id',
        'MusicBrainz Release Group Id',
        'MusicBrainz Release Track Id',
        'tmed',
        'SCRIPT',
        'originalyear',
        'artist',
        'album',
        'ALBUMARTIST',
        'title',
        'TORY',
        'tory',
        'TDOR',
        'tdor',
        'publisher',
        'TRACKNUMBER',
        'DISCNUMBER',
        'replaygain_track_peak',
        'replaygain_track_gain',
        'date',
        'language',
        'script',
        'tracknumber',
        'tlen',
        'album-sort',
        'isrc',
        'tsrc',
        'tracktotal',
        'disctotal',
        'discnumber',
        'cdtoc',
        'minor_version',
        'compilation',
        'lyrics',
        'description',
        'handler_name',
        'vendor_id',
        'compatible_brands',
        'major_brand',
        'encoding',
        'filesize',
        'album',
        'albumartist',
        'artist',
        'audio_offset',
        'bitrate',
        'channels',
        'comment',
        'composer',
        'disc',
        'disc_total',
        'duration',
        'genre',
        'samplerate',
        'title',
        'track',
        'track_total',
        'year',
    ]

    for key in known_tags:
        tags.pop(key, None)

    return tags


def parse_tags(m, tiny_tags):
    # breakpoint()
    tiny_tags.pop('extra', None)

    tags = {
        "albumgenre": combine(m.tags.get("albumgenre")),
        "albumgrouping": combine(m.tags.get("albumgrouping")),
        "mood": combine(
            list(
                set(
                    (m.tags.get("albummood") or [])
                    + (m.tags.get("MusicMatch_Situation") or [])
                    + (m.tags.get("Songs-DB_Occasion") or [])
                )
            )
        ),
        "genre": combine(list(set((m.tags.get("genre") or []) + list(filter(None, [tiny_tags["genre"]]))))),
        "year": safe_unpack(
            safe_unpack(
                list(
                    filter(
                        None,
                        [
                            m.tags.get("originalyear"),
                            m.tags.get("TDOR"),
                            m.tags.get("TORY"),
                            m.tags.get("date"),
                            m.tags.get("TDRC"),
                            m.tags.get("TDRL"),
                        ],
                    )
                ),
            ),
        ),
        "bpm": safe_unpack(
            safe_unpack(
                list(
                    filter(
                        None,
                        [m.tags.get("fBPM"), m.tags.get("bpm_accuracy")],
                    )
                ),
            ),
        ),
        "key": safe_unpack(
            safe_unpack(
                list(
                    filter(
                        None,
                        [
                            m.tags.get("TIT1"),
                            m.tags.get("key_accuracy"),
                            m.tags.get("TKEY"),
                        ],
                    )
                ),
            ),
        ),
        "gain": safe_unpack(0, m.tags.get("replaygain_track_gain")),
        "time": combine(safe_unpack(0, m.tags.get("time_signature"))),
        "decade": safe_unpack(0, m.tags.get("Songs-DB_Custom1")),
        "categories": safe_unpack(0, m.tags.get("Songs-DB_Custom2")),
        "city": safe_unpack(0, m.tags.get("Songs-DB_Custom3")),
        "country": combine(
            safe_unpack(
                list(
                    filter(
                        None,
                        [
                            m.tags.get("Songs-DB_Custom4"),
                            m.tags.get("MusicBrainz Album Release Country"),
                            m.tags.get("language"),
                        ],
                    )
                ),
            )
        ),
        "description": combine(
            safe_unpack(
                list(
                    filter(
                        None,
                        [
                            m.tags.get("description"),
                            m.tags.get("lyrics"),
                        ],
                    )
                ),
            )
        ),
    }

    try:
        new_tags = remove_known_tags(m)
    except:
        pass
    else:
        if len(new_tags.keys()) > 0:
            print(new_tags)

    # breakpoint()

    return tags
