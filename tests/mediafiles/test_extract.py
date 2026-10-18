import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from library.__main__ import library as lb
from library.mediafiles import extract


@pytest.fixture
def fake_media(monkeypatch, tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    probe = SimpleNamespace(
        video_streams=[{"index": 0}],
        audio_streams=[{"index": 1}, {"index": 3}],
        subtitle_streams=[{"index": 2}],
    )
    commands = []

    monkeypatch.setattr(extract.processes, "FFProbe", lambda _path: probe)

    def fake_cmd(*command, **_kwargs):
        commands.append(list(command))
        output = command[-1]
        if output != "-":
            output_path = Path(output)
            if "%" in output_path.name:
                output_path = output_path.with_name(output_path.name.replace("%05d", "00001").replace("%03d", "001"))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"output")
        stdout = "1\n00:00:00,000 --> 00:00:01,000\ncaption\n" if output == "-" else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(extract.processes, "cmd", fake_cmd)
    return source, commands


def test_extract_audio_copies_audio_stream(fake_media, tmp_path):
    source, commands = fake_media
    output = tmp_path / "audio.mka"

    lb(["video", "extract", "audio", str(source), "--output", str(output)])

    assert output.exists()
    assert commands[0][commands[0].index("-c:a") + 1] == "copy"
    assert "-vn" in commands[0]
    assert "-map" not in commands[0]


def test_extract_audio_can_map_all_streams(fake_media, tmp_path):
    source, commands = fake_media

    lb(["video", "extract", "audio", "--all-audio", str(source), "--output", str(tmp_path / "audio.mka")])

    assert commands[0][commands[0].index("-map") + 1] == "0:a"


def test_extract_subtitles_writes_selected_stream(fake_media, tmp_path):
    source, commands = fake_media
    output = tmp_path / "captions.srt"

    lb(["video", "extract", "subtitles", "--stream", "0", str(source), "--output", str(output)])

    assert output.exists()
    assert commands[0][commands[0].index("-map") + 1] == "0:2"
    assert commands[0][commands[0].index("-c:s") + 1] == "srt"


def test_extract_subtitles_supports_stdout(fake_media, capsys):
    source, commands = fake_media

    lb(["video", "extract", "subtitles", "--stdout", str(source)])

    assert "caption" in capsys.readouterr().out
    assert commands[0][-1] == "-"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ([], "setpts"),
        (["--images"], "select"),
        (["--contact-sheet"], "tile"),
    ],
)
def test_extract_scenes_modes(fake_media, command, expected):
    source, commands = fake_media

    lb(["video", "extract", "scenes", *command, "--threshold", "0.2", str(source)])

    assert expected in commands[0][commands[0].index("-vf") + 1]


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ([], "noise=drop=not(key)"),
        (["--images"], "PICT_TYPE_I"),
        (["--slow"], "setpts=N/FRAME_RATE/TB*8"),
    ],
)
def test_extract_keyframes_modes(fake_media, command, expected):
    source, commands = fake_media

    lb(["video", "extract", "keyframes", *command, str(source)])

    assert any(expected in " ".join(map(str, item)) for item in commands)
