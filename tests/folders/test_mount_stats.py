import sys

from library.folders import mount_stats


def test_mount_stats_prints_relative_usage(monkeypatch, capsys):
    monkeypatch.setattr(
        mount_stats,
        "get_mount_stats",
        lambda mounts: [{"mount": mounts[0], "used": 0.25, "free": 0.75}],
    )
    monkeypatch.setattr(sys, "argv", ["mount-stats", "/"])

    mount_stats.mount_stats()

    output = capsys.readouterr().out
    assert "Relative disk dependence:" in output
    assert "/: #################### 25.0%" in output
    assert "Relative free space:" in output
