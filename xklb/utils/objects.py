import itertools, json, types
from contextlib import contextmanager
from functools import wraps


class NoneSpace(types.SimpleNamespace):
    def __getattr__(self, name):
        return None


def fallback(func, fallback):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            return fallback

    return wrapped


def last_item(gen):
    last = None
    for _ in gen:
        last = _
    return last


def take(gen, num=5):
    for value, _ in zip(gen, range(num), strict=False):
        yield value


def gen_is_empty(generator):
    try:
        item = next(generator)

        def g2():
            yield item
            yield from generator

        return g2(), False
    except StopIteration:
        return (_ for _ in []), True


def gen_len(gen, max_length=100):
    items = []
    for count, item in enumerate(gen, start=1):
        items.append(item)
        if count >= max_length:
            break

    def new_generator():
        yield from items
        yield from gen

    return new_generator(), count


def flatten_dict(nested_dict, parent_key="", sep="_", passthrough_keys=None):
    if passthrough_keys is None:
        passthrough_keys = []
    flattened_dict = {}
    for key, value in nested_dict.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict) and key not in passthrough_keys:
            flattened_dict.update(flatten_dict(value, new_key, sep, passthrough_keys))
        else:
            flattened_dict[new_key] = value
    return flattened_dict


def flatten_grandparents(nested_dict, parent="", sep="_"):
    flattened_dict = {}

    for k, v in nested_dict.items():
        prefix = parent.split(sep)[-1]
        new_key = f"{prefix}{sep}{k}" if prefix else k

        if new_key in flattened_dict:
            flattened_dict.update(nested_dict)
        elif isinstance(v, dict):
            flattened_dict.update(flatten_grandparents(v, new_key, sep))
        else:
            flattened_dict[new_key] = v

    return flattened_dict


def flatten_dict_single_parents(nested_dict):
    flattened_dict = {}
    for k, v in nested_dict.items():
        if isinstance(v, dict) and len(v) == 1:
            next_key, next_v = flatten_dict_single_parents(v).popitem()
            flattened_dict[next_key] = next_v
        else:
            flattened_dict[k] = v
    return flattened_dict


def recursive_flattener(func, obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = recursive_flattener(func, v)
        return func(obj)
    elif isinstance(obj, list):
        return [recursive_flattener(func, i) for i in obj]
    else:
        return obj


def rename_key(d, from_key, to_key):
    d[to_key] = d.pop(from_key)
    return d


def lower_keys(d):
    for key in list(d.keys()):
        lower_key = key.lower().strip()
        if key != lower_key:
            rename_key(d, key, lower_key)
    return d


def dict_filter_bool(kwargs, keep_0=True) -> dict | None:
    if kwargs is None:
        return None

    if keep_0:
        filtered_dict = {k: v for k, v in kwargs.items() if v is not None and v != "" and v is not False}
    else:
        filtered_dict = {k: v for k, v in kwargs.items() if v}

    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def dict_filter_keys(kwargs, keys) -> dict | None:
    filtered_dict = {k: v for k, v in kwargs.items() if k not in keys}
    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def dumbcopy(d):
    return {i: j.copy() if type(j) == dict else j for i, j in d.items()}


def filter_namespace(args, config_opts) -> dict | None:
    return dict_filter_bool({k: v for k, v in args.__dict__.items() if k in config_opts})


@contextmanager
def json_shelve(filename, default):
    try:
        with open(filename) as f:
            stored_mappings = json.load(f)
            default.update(stored_mappings)

        yield default

        with open(filename, "w") as f:
            json.dump(default, f)

    except OSError:
        yield default


def is_profile(args, profile_target):
    if getattr(args, "profile", "") == profile_target:
        return True
    elif profile_target in getattr(args, "profiles", []):
        return True
    return False


def product(**kwargs):
    return (dict(zip(kwargs.keys(), x, strict=False)) for x in itertools.product(*kwargs.values()))


def class_enum(o):
    return [v for k, v in o.__dict__.items() if k and not k.startswith("__") and v]


def merge_dict_values_str(dict1, dict2):
    merged_dict = {}

    for key in set(dict1.keys()) | set(dict2.keys()):
        value1 = dict1.get(key, "")
        value2 = dict2.get(key, "")

        if value1.startswith(value2):
            merged_value = value1
        elif value2.startswith(value1):
            merged_value = value2
        else:
            merged_value = value1 + value2

        merged_dict[key] = merged_value

    return merged_dict


class Reverser:
    def __init__(self, obj):
        self.obj = obj

    def __lt__(self, other):
        return other.obj < self.obj

    def __eq__(self, other):
        return other.obj == self.obj

    def __repr__(self):
        return f"Reverse({self.obj})"


def replace_key_in_dict(d, old_key, new_key):
    if isinstance(d, dict):
        new_dict = {}
        for k, v in d.items():
            new_key_to_use = new_key if k == old_key else k
            new_dict[new_key_to_use] = replace_key_in_dict(v, old_key, new_key)
        return new_dict
    elif isinstance(d, list):
        return [replace_key_in_dict(item, old_key, new_key) for item in d]
    else:
        return d


def replace_keys_in_dict(d, replacements):
    for k, v in replacements.items():
        d = replace_key_in_dict(d, k, v)
    return d
