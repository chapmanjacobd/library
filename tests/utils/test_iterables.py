from library.utils import iterables
from tests.utils import take5


def test_flatten():
    assert list(iterables.flatten([[[[1]]]])) == [1]
    assert list(iterables.flatten([[[[1]], [2]]])) == [1, 2]
    assert list(iterables.flatten([[[["test"]]]])) == ["test"]
    assert list(iterables.flatten(take5())) == [0, 1, 2, 3, 4]
    assert list(iterables.flatten("")) == []
    assert list(iterables.flatten([""])) == [""]
    assert list(iterables.flatten([b"hello \xf0\x9f\x98\x81"])) == ["hello 😁"]
    assert list(iterables.flatten("[[[[1]]]]")) == ["[", "[", "[", "[", "1", "]", "]", "]", "]"]
    assert list(iterables.flatten(["[[[[1]]]]"])) == ["[[[[1]]]]"]


def test_conform():
    assert iterables.conform([[[[1]]]]) == [1]
    assert iterables.conform([[[[1]], [2]]]) == [1, 2]
    assert iterables.conform([[[["test"]]]]) == ["test"]
    assert iterables.conform(take5()) == [1, 2, 3, 4]
    assert iterables.conform("") == []
    assert iterables.conform([""]) == []
    assert iterables.conform(b"hello \xf0\x9f\x98\x81") == ["hello 😁"]
    assert iterables.conform("[[[[1]]]]") == ["[[[[1]]]]"]


def test_safe_unpack():
    assert iterables.safe_unpack(1, 2, 3, 4) == 1
    assert iterables.safe_unpack([1, 2, 3, 4]) == 1
    assert iterables.safe_unpack(None, "", 0, 1, 2, 3, 4) == 1
    assert iterables.safe_unpack([None, 1]) == 1
    assert iterables.safe_unpack([None]) is None
    assert iterables.safe_unpack(None) is None


def test_safe_pop():
    assert iterables.safe_pop([1, 2, 3]) == 3
    assert iterables.safe_pop([1, 2, 3], 0) == 1
    assert iterables.safe_pop([], 0) is None
    assert iterables.safe_pop(None) is None


def test_safe_len():
    assert iterables.safe_len([1, 2, 3]) == 3
    assert iterables.safe_len([]) == 0
    assert iterables.safe_len(None) == 0
    assert iterables.safe_len(123) == 3  # len of str(123)


def test_safe_index():
    assert iterables.safe_index([1, 2, 3], 2) == 1
    assert iterables.safe_index([1, 2, 3], 4) == -1
    assert iterables.safe_index([], 1) == 0
    assert iterables.safe_index(None, 1) == 0


def test_safe_sum():
    assert iterables.safe_sum(1, 2, 3, 4) == 10
    assert iterables.safe_sum([1, 2, 3, 4]) == 10
    assert iterables.safe_sum(None, "", 0, 1, 2, 3, 4) == 10
    assert iterables.safe_sum([None, 1]) == 1
    assert iterables.safe_sum([None]) is None
    assert iterables.safe_sum(None) is None
    assert iterables.safe_sum() is None
    assert iterables.safe_sum([0, 0, 0]) is None


def test_find_dict_value():
    data = [{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]
    assert iterables.find_dict_value(data, id=1) == {"id": 1, "val": "a"}
    assert iterables.find_dict_value(data, id=3) == {}
    assert iterables.find_dict_value(data, id=2, val="b") == {"id": 2, "val": "b"}


def test_list_dict_filter_bool():
    assert iterables.list_dict_filter_bool([{"t": 1}]) == [{"t": 1}]
    assert iterables.list_dict_filter_bool([{"t": None}]) == []
    assert iterables.list_dict_filter_bool([]) == []
    assert iterables.list_dict_filter_bool([{}]) == []


def test_list_dict_unique():
    data = [{"id": 1, "val": "a"}, {"id": 1, "val": "b"}, {"id": 2, "val": "a"}]
    assert len(iterables.list_dict_unique(data, ["id"])) == 2
    assert len(iterables.list_dict_unique(data, ["val"])) == 2
    assert len(iterables.list_dict_unique(data, ["id", "val"])) == 3


def test_chunks():
    assert list(iterables.chunks([1, 2, 3], 1)) == [[1], [2], [3]]
    assert list(iterables.chunks([1, 2, 3], 2)) == [[1, 2], [3]]
    assert list(iterables.chunks([1, 2, 3], 4)) == [[1, 2, 3]]


def test_divisors_upto_sqrt():
    for v in [0, 1, 2, 3, 5, 7]:
        assert sorted(iterables.divisors_upto_sqrt(v)) == []
    assert sorted(iterables.divisors_upto_sqrt(4)) == [2]
    assert sorted(iterables.divisors_upto_sqrt(6)) == [2, 3]
    assert sorted(iterables.divisors_upto_sqrt(8)) == [2, 4]
    assert sorted(iterables.divisors_upto_sqrt(9)) == [3]
    assert sorted(iterables.divisors_upto_sqrt(10)) == [2, 5]
    assert sorted(iterables.divisors_upto_sqrt(100)) == [2, 4, 5, 10, 20, 25, 50]


def test_similarity():
    assert iterables.similarity([1, 2, 3], [1, 2, 3]) == 1.0
    assert iterables.similarity([1, 2, 3], [4, 5, 6]) == 0.0
    assert iterables.similarity([1, 2], [2, 3]) == 1 / 3
    assert iterables.similarity([], []) == 0.0
    assert iterables.similarity(None, None) == 0.0


def test_concat():
    assert list(iterables.concat([1], [2], [], [3])) == [[1], [2], [3]]


def test_ordered_set():
    assert list(iterables.ordered_set([1, 2, 2, 3, 1])) == [1, 2, 3]
    assert list(iterables.ordered_set([])) == []


def test_value_counts():
    assert iterables.value_counts([1, 2, 2, 3, 1, 1]) == [3, 2, 2, 1, 3, 3]


def test_divide_sequence():
    assert iterables.divide_sequence([100, 2, 5]) == 10.0
    assert iterables.divide_sequence([10, 0]) == float("-inf")
    assert iterables.divide_sequence([0, 10]) == float("inf")
