import json

import pytest

from xklb.__main__ import library as lb
from xklb.utils import consts


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
