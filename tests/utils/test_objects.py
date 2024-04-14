from xklb.utils import objects


def test_dict_filter_bool():
    assert objects.dict_filter_bool({"t": 0}) == {"t": 0}
    assert objects.dict_filter_bool({"t": 0}, keep_0=False) is None
    assert objects.dict_filter_bool({"t": 1}) == {"t": 1}
    assert objects.dict_filter_bool({"t": None, "t1": 1}) == {"t1": 1}
    assert objects.dict_filter_bool({"t": None}) is None
    assert objects.dict_filter_bool({"t": ""}) is None
    assert objects.dict_filter_bool(None) is None
