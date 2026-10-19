import random
from pathlib import Path

from natsort import natsorted

from library.__main__ import library as lb
from library.video import create


def concat_path(path):
    return str(path.resolve()).replace("\\", "\\\\").replace("'", "'\\''")


def fake_ffmpeg(monkeypatch):
    commands = []

    def run(*command, **_kwargs):
        commands.append(list(command))
        output = Path(command[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"output")

    monkeypatch.setattr(create.processes, "cmd", run)
    return commands


def test_images_to_video_builds_slideshow_command(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    first = tmp_path / "image-02.jpg"
    second = tmp_path / "image-01.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    output = tmp_path / "slideshow.mp4"

    lb(["video", "create", "images", "--picture-time", "3", "--output", str(output), str(first), str(second)])

    assert output.exists()
    assert commands[0][commands[0].index("-f") + 1] == "concat"
    assert commands[0][commands[0].index("-r") + 1] == "25"


def test_images_to_video_builds_crossfade_filter(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    lb(
        [
            "video",
            "create",
            "images",
            "--picture-time",
            "4",
            "--crossfade-time",
            "0.5",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            str(first),
            str(second),
        ]
    )

    assert "xfade=transition=fade:duration=0.5:offset=3.5" in commands[0][commands[0].index("-filter_complex") + 1]


def test_images_to_video_fits_audio_duration(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    audio = tmp_path / "music.m4a"
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    audio.write_bytes(b"audio")
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 10

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(
        [
            "video",
            "create",
            "images",
            "--audio",
            str(audio),
            "--audio-duration",
            "--crossfade-time",
            "0.5",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            str(first),
            str(second),
        ]
    )

    command = commands[0]
    assert str(audio) in command
    assert command[command.index("-map") + 1] == "[xf1]"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "2:a:0"
    assert "-shortest" in command
    assert "-t" in command
    assert command[command.index("-t") + 1] == "5.25"


def test_images_to_video_repeats_images_until_audio_ends(monkeypatch, tmp_path):
    commands = []
    list_contents = []

    def run(command, _args):
        commands.append(command)
        list_contents.append(Path(command[command.index("-i") + 1]).read_text())
        Path(command[-1]).write_bytes(b"output")

    monkeypatch.setattr(create, "_run", run)
    audio = tmp_path / "music.m4a"
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    audio.write_bytes(b"audio")
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 20

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(
        [
            "video",
            "create",
            "images",
            "--audio",
            str(audio),
            "--loop-images",
            "--picture-time",
            "3",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            str(first),
            str(second),
        ]
    )

    command = commands[0]
    assert list_contents[0].count("file ") == 9
    assert command[command.index("-map") + 1] == "0:v:0"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "1:a:0"
    assert "-shortest" in command


def test_images_to_video_holds_last_image_until_audio_ends(monkeypatch, tmp_path):
    commands = []
    list_contents = []

    def run(command, _args):
        commands.append(command)
        list_contents.append(Path(command[command.index("-i") + 1]).read_text())
        Path(command[-1]).write_bytes(b"output")

    monkeypatch.setattr(create, "_run", run)
    audio = tmp_path / "music.m4a"
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    audio.write_bytes(b"audio")
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 20

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(
        [
            "video",
            "create",
            "images",
            "--audio",
            str(audio),
            "--hold-last-image",
            "--picture-time",
            "3",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            str(first),
            str(second),
        ]
    )

    assert len(commands) == 1
    assert list_contents[0].count("file ") == 8
    assert list_contents[0].count(concat_path(second)) == 7


def test_images_to_video_loops_audio_and_applies_audio_options(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    audio = tmp_path / "music.m4a"
    first = tmp_path / "first.jpg"
    audio.write_bytes(b"audio")
    first.write_bytes(b"first")

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 20

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(
        [
            "video",
            "create",
            "images",
            "--audio",
            str(audio),
            "--loop-audio",
            "--audio-fade-in",
            "1",
            "--audio-fade-out",
            "2",
            "--audio-volume",
            "0.5",
            "--fit",
            "crop",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            str(first),
        ]
    )

    command = commands[0]
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert "crop=1280:720" in command[command.index("-vf") + 1]
    audio_filter = command[command.index("-af") + 1]
    assert audio_filter.startswith("volume=0.5,afade=t=in:st=0:d=1,afade=t=out:")
    assert audio_filter.endswith(":d=2")


def test_images_to_video_shuffles_with_seed_and_applies_stretch(monkeypatch, tmp_path):
    commands = []
    list_contents = []

    def run(command, _args):
        commands.append(command)
        list_contents.append(Path(command[command.index("-i") + 1]).read_text())
        Path(command[-1]).write_bytes(b"output")

    monkeypatch.setattr(create, "_run", run)
    paths = [tmp_path / name for name in ("one.jpg", "two.jpg", "three.jpg")]
    for path in paths:
        path.write_bytes(path.name.encode())

    lb(
        [
            "video",
            "create",
            "images",
            "--shuffle",
            "--seed",
            "42",
            "--fit",
            "stretch",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            *map(str, paths),
        ]
    )

    assert "scale=1280:720,format=yuv420p" in commands[0][commands[0].index("-vf") + 1]
    shuffled = natsorted(paths)
    random.Random(42).shuffle(shuffled)
    assert list_contents[0].splitlines()[0].endswith(f"{concat_path(shuffled[0])}'")


def test_images_to_video_builds_ken_burns_motion(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    first = tmp_path / "first.jpg"
    first.write_bytes(b"first")

    lb(
        [
            "video",
            "create",
            "images",
            "--motion",
            "ken-burns",
            "--motion-zoom",
            "1.2",
            "--output",
            str(tmp_path / "slideshow.mp4"),
            str(first),
        ]
    )

    command = commands[0]
    assert "-framerate" in command
    assert "zoompan=" in command[command.index("-filter_complex") + 1]
    assert "1.2" in command[command.index("-filter_complex") + 1]


def test_images_to_video_concats_repeated_audio_flags(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    audio_one = tmp_path / "intro.opus"
    audio_two = tmp_path / "main.opus"
    image = tmp_path / "image.jpg"
    for path in (audio_one, audio_two, image):
        path.write_bytes(path.name.encode())
    output = tmp_path / "slideshow.mp4"

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 10

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(
        [
            "video",
            "create",
            "slideshow",
            "--audio",
            str(audio_one),
            "--audio",
            str(audio_two),
            "--output",
            str(output),
            str(image),
        ]
    )

    command = commands[0]
    assert output.exists()
    assert command.count("-i") == 3
    assert "concat=n=2:v=0:a=1[audio]" in command[command.index("-filter_complex") + 1]
    assert "[audio]" in command


def test_images_to_video_expands_audio_directory(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    audio_one = audio_dir / "track-02.opus"
    audio_two = audio_dir / "track-01.opus"
    image = tmp_path / "image.jpg"
    for path in (audio_one, audio_two, image):
        path.write_bytes(path.name.encode())

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 10

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(["video", "create", "slideshow", "--audio", str(audio_dir), str(image)])

    command = commands[0]
    assert command.index(str(audio_two)) < command.index(str(audio_one))


def test_slideshow_without_images_uses_black_background(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    source = tmp_path / "recording.opus"
    source.write_bytes(b"audio")
    output = tmp_path / "recording.mp4"

    class Probe:
        def __init__(self):
            self.audio_streams = [{"codec_type": "audio"}]
            self.duration = 10

    monkeypatch.setattr(create.processes, "FFProbe", lambda _path: Probe())

    lb(["video", "create", "slideshow", "--audio", str(source), "--output", str(output)])

    command = commands[0]
    assert output.exists()
    assert "color=c=black:s=1280x720:r=25" in command
    assert command[command.index("-map") + 1] == "0:v:0"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "1:a:0"


def test_video_concat_cleans_temporary_list(monkeypatch, tmp_path):
    commands = fake_ffmpeg(monkeypatch)
    first = tmp_path / "one.mkv"
    second = tmp_path / "two.mkv"
    output = tmp_path / "joined.mkv"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    lb(["video", "concat", str(output), str(first), str(second)])

    assert output.exists()
    command = commands[0]
    list_path = Path(command[command.index("-i") + 1])
    assert not list_path.exists()
    assert command[command.index("-c") + 1] == "copy"
