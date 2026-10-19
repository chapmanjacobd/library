from types import SimpleNamespace
from unittest.mock import Mock

from library.utils.gui import MrSuperDialogue


def test_get_coord_offset_from_monitor():
    monitor = SimpleNamespace(x=-1920, y=48)

    assert MrSuperDialogue._get_coord_offset_from_monitor(monitor) == (-1920, 48)  # noqa: SLF001


def test_move_window_preserves_absolute_monitor_coordinates():
    dialogue = object.__new__(MrSuperDialogue)
    dialogue.root = Mock()

    dialogue.move_window(640, 480, -1920, 48)

    dialogue.root.geometry.assert_called_once_with("640x480+-1920+48")
    dialogue.root.wm_attributes.assert_called_once_with("-alpha", 1)
