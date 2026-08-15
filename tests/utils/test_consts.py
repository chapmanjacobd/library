from library.utils import consts


def test_no_audio_image_extension_overlap():
    # C10: wav/riff/rif appear in both AUDIO_ONLY_EXTENSIONS and IMAGE_EXTENSIONS,
    # making --audio and --image classification ambiguous.
    assert not consts.AUDIO_ONLY_EXTENSIONS & consts.IMAGE_EXTENSIONS


def test_quarterly_days_consistent():
    # C11: tabs_add.get_days() maps quarterly -> 89 while tabs_open.frequency_filter uses 91.
    from library.createdb.tabs_add import get_days

    assert get_days("quarterly") == 91


def test_all_consts_frequency_served():
    # C12: consts.frequency advertises minutely/hourly/decadally but tabs_open's mapper
    # falls back to a 365-day default, and sqlgroups' CASE produces time_valid=NULL, so
    # tabs with those frequencies can never open.
    mapper = {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
        "quarterly": 91,
        "yearly": 365,
    }
    for freq in consts.frequency:
        assert freq in mapper, f"{freq} frequency is advertised but has no serving period"


def test_dedupe_media_constant_matches_action():
    # C13: SC.dedupe_media = "dedupe" but the real action name is "dedupe-media"
    assert consts.SC.dedupe_media == "dedupe-media"
