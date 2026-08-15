import sys

from library.mediadb import history


def test_history_accepts_frequency_flag():
    # C5: usage.history documents `--frequency` but parse_args never registers the
    # arggroup, so the documented flag errors with "unrecognized arguments".
    sys.argv = ["lb", "history", "tests/data/audio.db", "--frequency", "daily"]
    args = history.parse_args()
    assert args.frequency == "daily"
