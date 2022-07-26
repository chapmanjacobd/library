import re
from typing import Dict

from utils import flatten

_RE_COMBINE_WHITESPACE = re.compile(r"\s+")


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

    no_comma = sum([s.split(',') for s in list_], [])
    no_semicol = sum([s.split(';') for s in no_comma], [])
    no_double_space = [_RE_COMBINE_WHITESPACE.sub(' ', s).strip() for s in no_semicol]
    no_unknown = [x for x in no_double_space if x.lower() not in ['unknown', 'none', 'und', '']]

    no_duplicates = list(set(no_unknown))
    return ';'.join(no_duplicates)


def safe_unpack(*list_, idx=0):
    list_ = conform(list_)
    if len(list_) == 0:
        return None

    try:
        return list_[idx]
    except IndexError:
        return None


def parse_tags(mutagen: Dict, tinytag: Dict):
    tags = {
        'mood': combine(
            mutagen.get('albummood'),
            mutagen.get('MusicMatch_Situation'),
            mutagen.get('Songs-DB_Occasion'),
            mutagen.get('albumgrouping'),
        ),
        'genre': combine(mutagen.get('genre'), tinytag.get('genre'), mutagen.get('albumgenre')),
        'year': safe_unpack(
            mutagen.get('originalyear'),
            mutagen.get('TDOR'),
            mutagen.get('TORY'),
            mutagen.get('date'),
            mutagen.get('TDRC'),
            mutagen.get('TDRL'),
        ),
        'bpm': safe_unpack(mutagen.get('fBPM'), mutagen.get('bpm_accuracy')),
        'key': safe_unpack(mutagen.get('TIT1'), mutagen.get('key_accuracy'), mutagen.get('TKEY')),
        'gain': safe_unpack(mutagen.get('replaygain_track_gain')),
        'time': combine(mutagen.get('time_signature')),
        'decade': safe_unpack(mutagen.get('Songs-DB_Custom1')),
        'categories': safe_unpack(mutagen.get('Songs-DB_Custom2')),
        'city': safe_unpack(mutagen.get('Songs-DB_Custom3')),
        'country': combine(
            mutagen.get('Songs-DB_Custom4'),
            mutagen.get('MusicBrainz Album Release Country'),
            mutagen.get('musicbrainz album release country'),
            mutagen.get('language'),
        ),
        'description': combine(
            mutagen.get('description'),
            mutagen.get('lyrics'),
            tinytag.get('comment'),
        ),
        'album': safe_unpack(tinytag.get('album'), mutagen.get('album')),
        'title': safe_unpack(tinytag.get('title'), mutagen.get('title')),
        'artist': combine(
            tinytag.get('artist'),
            mutagen.get('artist'),
            mutagen.get('artists'),
            tinytag.get('albumartist'),
            tinytag.get('composer'),
        ),
    }

    # print(mutagen)
    # breakpoint()

    return tags
