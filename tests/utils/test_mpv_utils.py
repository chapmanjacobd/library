import argparse, time
from pathlib import Path

from xklb.utils import consts, mpv_utils


def test_mpv_md5():
    assert (
        mpv_utils.path_to_mpv_watchlater_md5("/home/xk/github/xk/lb/tests/data/test.mp4")
        == "E1E0D0E3F0D2CB748303FDA43224B7E7"
    )


def test_get_playhead():
    args = argparse.Namespace(
        mpv_socket=consts.DEFAULT_MPV_LISTEN_SOCKET,
        watch_later_directory=consts.DEFAULT_MPV_WATCH_LATER,
    )
    path = str(Path("/home/runner/work/library/library/tests/data/test.mp4").resolve())
    md5 = mpv_utils.path_to_mpv_watchlater_md5(path)
    metadata_path = Path(consts.DEFAULT_MPV_WATCH_LATER, md5).expanduser().resolve()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)

    # use MPV time
    start_time = time.time() - 2
    Path(metadata_path).write_text("start=5.000000")
    assert mpv_utils.get_playhead(args, path, start_time) == 5
    # check invalid MPV time
    Path(metadata_path).write_text("start=13.000000")
    assert mpv_utils.get_playhead(args, path, start_time, media_duration=12) == 2

    # use python time only if MPV does not exist
    assert mpv_utils.get_playhead(args, path, start_time) == 13
    Path(metadata_path).unlink()
    assert mpv_utils.get_playhead(args, path, start_time) == 2
    # append existing time
    start_time = time.time() - 3
    assert mpv_utils.get_playhead(args, path, start_time, existing_playhead=4, media_duration=12) == 7
    # unless invalid
    assert mpv_utils.get_playhead(args, path, start_time, existing_playhead=10, media_duration=12) is None
    start_time = time.time() - 10
    assert mpv_utils.get_playhead(args, path, start_time, existing_playhead=3, media_duration=12) is None
