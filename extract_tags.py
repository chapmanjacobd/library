from copy import deepcopy
import sys
from typing import Dict
from utils import flatten

def conform(list_):
    if not isinstance(list_, list):
        list_ = [list_]
    list_ = flatten(list_)
    list_ = list(filter(None, list_))
    return list_

def combine(*list_):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    no_comma = sum([s.split(",") for s in list_], [])
    no_semicol = sum([s.split(";") for s in no_comma], [])
    no_unknown = [x for x in no_semicol if x.lower() not in ["unknown", ""]]

    no_duplicates = list(set(no_unknown))
    return ";".join(no_duplicates)


def safe_unpack(*list_, idx=0):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    try:
        return list_[idx]
    except IndexError:
        return None


def remove_known_tags(all_tags, ignore):
    new_tags = deepcopy(all_tags)

    known_tags = ignore + [
        'ASIN',
        'Acoustid Id',
        'BARCODE',
        'CATALOGNUMBER',
        'DISCNUMBER',
        'MusicBrainz Album Artist Id',
        'MusicBrainz Album Id',
        'MusicBrainz Album Status',
        'MusicBrainz Album Type',
        'MusicBrainz Artist Id',
        'MusicBrainz Release Group Id',
        'MusicBrainz Release Track Id',
        'MusicBrainz Album Release Country',
        'SCRIPT',
        'TDOR',
        'TMED',
        'TORY',
        'TRACKNUMBER',
        'TSO2',
        'album-sort',
        'artist-sort',
        'audio_offset',
        'bitrate',
        'cdtoc',
        'channels',
        'comment',
        'compatible_brands',
        'compilation',
        'date',
        'description',
        'disc',
        'disc_total',
        'discnumber',
        'disctotal',
        'duration',
        'encoder',
        'encoding',
        'filesize',
        'genre',
        'handler_name',
        'isrc',
        'language',
        'lyrics',
        'major_brand',
        'minor_version',
        'originalyear',
        'publisher',
        'replaygain_track_gain',
        'replaygain_track_peak',
        'samplerate',
        'script',
        'tdor',
        'tlen',
        'tmed',
        'tory',
        'track',
        'track_total',
        'tracknumber',
        'tracktotal',
        'tsrc',
        'vendor_id',
        'year',
    ]

    for key in known_tags:
        new_tags.pop(key, None)

    return new_tags


def parse_tags(mutagen: Dict, tinytag: Dict):
    all_tags = {**mutagen, **tinytag}

    tags = {
        "albumgenre": combine(mutagen.get("albumgenre")),
        "albumgrouping": combine(mutagen.get("albumgrouping")),
        "mood": combine(
            mutagen.get("albummood"),
            mutagen.get("MusicMatch_Situation"),
            mutagen.get("Songs-DB_Occasion"),
        ),
        "genre": combine(mutagen.get("genre"), tinytag["genre"]),
        "year": safe_unpack(
            mutagen.get("originalyear"),
            mutagen.get("TDOR"),
            mutagen.get("TORY"),
            mutagen.get("date"),
            mutagen.get("TDRC"),
            mutagen.get("TDRL"),
        ),
        "bpm": safe_unpack(mutagen.get("fBPM"), mutagen.get("bpm_accuracy")),
        "key": safe_unpack(mutagen.get("TIT1"), mutagen.get("key_accuracy"), mutagen.get("TKEY")),
        "gain": safe_unpack(mutagen.get("replaygain_track_gain")),
        "time": combine(mutagen.get("time_signature")),
        "decade": safe_unpack(mutagen.get("Songs-DB_Custom1")),
        "categories": safe_unpack(mutagen.get("Songs-DB_Custom2")),
        "city": safe_unpack(mutagen.get("Songs-DB_Custom3")),
        "country": combine(
            mutagen.get("Songs-DB_Custom4"), mutagen.get("MusicBrainz Album Release Country"), mutagen.get("language")
        ),
        "description": combine(
            mutagen.get("description"),
            mutagen.get("lyrics"),
        ),
    }

    try:
        new_tags = remove_known_tags(all_tags, tags.keys())
    except:
        pass
    else:
        if len(new_tags.keys()) > 0:
            print(new_tags)

    breakpoint()

    return tags
