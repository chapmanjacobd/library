import json

from library.__main__ import library as lb
from library.text import cluster_sort
from library.utils.objects import NoneSpace


def test_lb_cs_lines(mock_stdin, capsys):
    with mock_stdin(
        """red apple
broccoli
yellow
green
orange apple
red apple"""
    ):
        lb(["cluster-sort"])

    captured = capsys.readouterr().out
    assert (
        captured
        == """orange apple
red apple
red apple
broccoli
green
yellow
"""
    )


def test_lb_cs_wordllama_groups(mock_stdin, capsys):
    with mock_stdin(
        """red apple
broccoli
yellow
green
orange apple
red apple"""
    ):
        lb(["cluster-sort", "--print-groups"])
    captured = capsys.readouterr().out
    assert json.loads(captured) == [
        {"common_path": "*apple*red", "grouped_paths": ["orange apple", "red apple", "red apple"]},
        {"common_path": "*", "grouped_paths": ["broccoli", "green", "yellow"]},
    ]


def test_lb_cs_tfidf_groups(mock_stdin, capsys):
    with mock_stdin(
        """red apple
broccoli
yellow
green
orange apple
red apple"""
    ):
        lb(["cluster-sort", "--print-groups", "--tfidf"])

    captured = capsys.readouterr().out
    assert json.loads(captured) == [
        {"common_path": "*apple*red", "grouped_paths": ["orange apple", "red apple", "red apple"]},
        {"common_path": "*", "grouped_paths": ["broccoli", "green", "yellow"]},
    ]


def test_lb_cs_duplicates(mock_stdin, capsys):
    with mock_stdin(
        """red apple
broccoli
yellow
green
orange apple
red apple"""
    ):
        lb(["cluster-sort", "--duplicates", "--print-groups"])
    captured = capsys.readouterr().out
    assert json.loads(captured) == [
        {"common_path": "*apple*red#0", "grouped_paths": ["orange apple", "red apple", "red apple"]},
        {"common_path": "*#0", "grouped_paths": ["broccoli"]},
        {"common_path": "*#1", "grouped_paths": ["green"]},
        {"common_path": "*#2", "grouped_paths": ["yellow"]},
    ]


def test_cluster_paths_returns_groups_for_short_input():
    groups = cluster_sort.cluster_paths(None, ["one", "two"])

    assert [group["grouped_paths"] for group in groups] == [["one"], ["two"]]


def test_image_groups_use_neighbor_identities():
    groups = cluster_sort._groups_from_neighbors(
        ["first.png", "second.png", "third.png"],
        [[1], [0], [2]],
    )

    assert [group["grouped_paths"] for group in groups] == [["first.png", "second.png"], ["third.png"]]


def test_sort_dicts_reverses_duration_groups(monkeypatch):
    monkeypatch.setattr(cluster_sort, "find_clusters", lambda _args, _sentences: [0, 0, 1])
    args = NoneSpace(verbose=0, sort_groups_by="duration desc")
    media = [
        {"path": "first", "duration": 10},
        {"path": "second", "duration": 20},
        {"path": "third", "duration": 30},
    ]

    assert [m["path"] for m in cluster_sort.sort_dicts(args, media)] == ["second", "first", "third"]
