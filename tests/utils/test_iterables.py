from library.utils import iterables
from tests.utils import take5


def test_flatten():
    assert list(iterables.flatten([[[[1]]]])) == [1]
    assert list(iterables.flatten([[[[1]], [2]]])) == [1, 2]
    assert list(iterables.flatten([[[["test"]]]])) == ["test"]
    assert list(iterables.flatten(take5())) == [0, 1, 2, 3, 4]
    assert list(iterables.flatten("")) == []
    assert list(iterables.flatten([""])) == [""]
    assert list(iterables.flatten([b"hello \xF0\x9F\x98\x81"])) == ["hello 😁"]
    assert list(iterables.flatten("[[[[1]]]]")) == ["[", "[", "[", "[", "1", "]", "]", "]", "]"]
    assert list(iterables.flatten(["[[[[1]]]]"])) == ["[[[[1]]]]"]


def test_conform():
    assert iterables.conform([[[[1]]]]) == [1]
    assert iterables.conform([[[[1]], [2]]]) == [1, 2]
    assert iterables.conform([[[["test"]]]]) == ["test"]
    assert iterables.conform(take5()) == [1, 2, 3, 4]
    assert iterables.conform("") == []
    assert iterables.conform([""]) == []
    assert iterables.conform(b"hello \xF0\x9F\x98\x81") == ["hello 😁"]
    assert iterables.conform("[[[[1]]]]") == ["[[[[1]]]]"]


def test_safe_unpack():
    assert iterables.safe_unpack(1, 2, 3, 4) == 1
    assert iterables.safe_unpack([1, 2, 3, 4]) == 1
    assert iterables.safe_unpack(None, "", 0, 1, 2, 3, 4) == 1
    assert iterables.safe_unpack([None, 1]) == 1
    assert iterables.safe_unpack([None]) is None
    assert iterables.safe_unpack(None) is None


def test_safe_sum():
    assert iterables.safe_sum(1, 2, 3, 4) == 10
    assert iterables.safe_sum([1, 2, 3, 4]) == 10
    assert iterables.safe_sum(None, "", 0, 1, 2, 3, 4) == 10
    assert iterables.safe_sum([None, 1]) == 1
    assert iterables.safe_sum([None]) is None
    assert iterables.safe_sum(None) is None
    assert iterables.safe_sum() is None
    assert iterables.safe_sum([0, 0, 0]) is None


def test_list_dict_filter_bool():
    assert iterables.list_dict_filter_bool([{"t": 1}]) == [{"t": 1}]
    assert iterables.list_dict_filter_bool([{"t": None}]) == []
    assert iterables.list_dict_filter_bool([]) == []
    assert iterables.list_dict_filter_bool([{}]) == []


def test_chunks():
    assert list(iterables.chunks([1, 2, 3], 1)) == [[1], [2], [3]]
    assert list(iterables.chunks([1, 2, 3], 2)) == [[1, 2], [3]]
    assert list(iterables.chunks([1, 2, 3], 4)) == [[1, 2, 3]]


def test_divisor_gen():
    for v in [0, 1, 2, 3, 5, 7]:
        assert sorted(iterables.divisors_upto_sqrt(v)) == []
    assert sorted(iterables.divisors_upto_sqrt(4)) == [2]
    assert sorted(iterables.divisors_upto_sqrt(6)) == [2, 3]
    assert sorted(iterables.divisors_upto_sqrt(8)) == [2, 4]
    assert sorted(iterables.divisors_upto_sqrt(9)) == [3]
    assert sorted(iterables.divisors_upto_sqrt(10)) == [2, 5]
    assert sorted(iterables.divisors_upto_sqrt(100)) == [2, 4, 5, 10, 20, 25, 50]
