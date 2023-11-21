import math
from collections.abc import Iterable
from functools import wraps
from typing import Any, Iterator, List, Optional, Union

from xklb.utils import objects


def flatten(xs: Iterable) -> Iterator:
    for x in xs:
        if isinstance(x, Iterable) and not isinstance(x, (str, bytes)):
            yield from flatten(x)
        elif isinstance(x, bytes):
            yield x.decode("utf-8")
        else:
            yield x


def conform(list_: Union[str, Iterable]) -> List:
    if not list_:
        return []
    if not isinstance(list_, list):
        list_ = [list_]
    list_ = flatten(list_)
    list_ = list(filter(bool, list_))
    return list_


def safe_unpack(*list_, idx=0, keep_0=True) -> Optional[Any]:
    list_ = conform(list_)
    if not list_:
        return None

    try:
        value = list_[idx]
        return value if keep_0 or value != 0 else None
    except IndexError:
        return None


def safe_pop(list_, idx=-1) -> Optional[Any]:
    if not list_:
        return None
    return list_[idx]


def get_all_lists(nested_dict):
    list_ = []

    for value in nested_dict.values():
        if isinstance(value, list):
            list_.append(value)
        elif isinstance(value, dict):
            list_.extend(get_all_lists(value))

    return list_


def get_list_with_most_items(nested_dict):
    list_ = get_all_lists(nested_dict)
    list_ = sorted(list_, key=len)
    return safe_pop(list_)


def safe_sum(*list_, keep_0=False) -> Optional[Any]:
    list_ = conform(list_)
    if not list_:
        return None
    value = sum(list_)
    return value if keep_0 or value != 0 else None


def concat(*args):
    return (part for part in args if part)


def find_none_keys(list_of_dicts, keep_0=True):
    none_keys = []

    if not list_of_dicts:
        return none_keys

    keys = list_of_dicts[0].keys()
    for key in keys:
        is_key_none = True
        for d in list_of_dicts:
            value = d.get(key)
            if value or (keep_0 and value == 0):
                is_key_none = False
                break
        if is_key_none:
            none_keys.append(key)

    return none_keys


def list_dict_filter_bool(media: List[dict], keep_0=True) -> List[dict]:
    keys_to_remove = find_none_keys(media, keep_0=keep_0)
    return [d for d in [{k: v for k, v in m.items() if k not in keys_to_remove} for m in media] if d]


def list_dict_filter_keys(media: List[dict], keys) -> List[dict]:
    return [d for d in [objects.dict_filter_keys(d, keys) for d in media] if d]


def list_dict_filter_unique(data: List[dict]) -> List[dict]:
    if len(data) == 0:
        return []

    unique_values = {}
    for key in set.intersection(*(set(d.keys()) for d in data)):
        values = {d[key] for d in data if key in d}
        if len(values) > 1:
            unique_values[key] = values
    filtered_data = [{k: v for k, v in d.items() if k in unique_values} for d in data]
    return filtered_data


def list_dict_unique(data: List[dict], unique_keys: List[str]) -> List[dict]:
    seen = set()
    list_ = []
    for d in data:
        t = tuple(d[key] for key in unique_keys)

        if t not in seen:
            seen.add(t)
            list_.append(d)

    return list_


def chunks(lst, n) -> Iterator:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def divisors_upto_sqrt(n: int) -> Iterator:
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:
            yield i
            if i * i != n:
                yield int(n / i)


def ordered_set(items):
    seen = set()
    for item in items:
        if item not in seen:
            yield item
            seen.add(item)


def return_unique(gen_func):
    seen = set()

    @wraps(gen_func)
    def wrapper(*args, **kwargs):
        for item in gen_func(*args, **kwargs):
            if item in seen:
                continue
            seen.add(item)
            yield item

    return wrapper


def return_unique_set_items(gen_func):
    seen = set()

    def wrapper(*args, **kwargs):
        for item in gen_func(*args, **kwargs):
            diff = item - seen
            if diff:
                seen.update(item)
                yield diff

    return wrapper


def multi_split(string, delimiters):
    delimiters = tuple(delimiters)
    stack = [
        string,
    ]

    for delimiter in delimiters:
        for i, substring in enumerate(stack):
            substack = substring.split(delimiter)
            stack.pop(i)
            for j, _substring in enumerate(substack):
                stack.insert(i + j, _substring)

    return stack
