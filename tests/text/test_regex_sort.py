from xklb.__main__ import library as lb


def test_lb_rs_stdin(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(
        """red apple
broccoli
yellow
green
orange apple
red apple"""
    ):
        lb(["regex-sort"])

    captured = capsys.readouterr().out
    assert_unchanged(captured.strip().split("\n"))


def test_lb_rs_stdin_linesort_dup(mock_stdin, assert_unchanged, capsys):
    with mock_stdin(
        """red apple
broccoli
yellow
green
orange apple
red apple"""
    ):
        lb(["regex-sort", "--line-sort", "dup,natsort"])

    captured = capsys.readouterr().out
    assert_unchanged(captured.strip().split("\n"))
