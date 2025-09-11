from library.utils.processes import adjust_duration


def test_duration_adjusted_with_start_and_end_time():
    assert adjust_duration(100.0, 10.0, 50.0) == 40.0


def test_duration_adjusted_with_only_start_time():
    assert adjust_duration(100.0, 10.0, None) == 90.0


def test_duration_with_start_time_greater_than_duration():
    assert adjust_duration(100.0, 150.0, 200.0) == 100.0


def test_start_time_equals_end_time():
    assert adjust_duration(100.0, 50.0, 50.0) == 50.0


def test_start_time_greater_than_end_time():
    assert adjust_duration(100.0, 60.0, 50.0) == 40.0


def test_no_adjustment_with_zero_start_time():
    assert adjust_duration(100.0, 0, 50) == 50


def test_no_adjustment_with_negative_start_time():
    assert adjust_duration(100.0, -10, 50) == 100.0


def test_no_adjustment_with_zero_duration():
    assert adjust_duration(0, 10, 50) == 0


def test_no_adjustment_with_none_values():
    assert adjust_duration(100.0, None, None) == 100.0
    assert adjust_duration(100.0, 100.0, None) == 100.0
    assert adjust_duration(100.0, None, 100.0) == 100.0
