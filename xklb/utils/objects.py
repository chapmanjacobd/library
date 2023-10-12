from typing import Dict, Optional

from xklb.utils.log_utils import log


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


def lower_keys(input_dict):
    output_dict = {}
    for key, value in input_dict.items():
        lowercase_key = key.lower().strip()
        if lowercase_key in output_dict:
            log.warning("Overriding key %s: %s -> %s", lowercase_key, output_dict[lowercase_key], value)
        output_dict[lowercase_key] = value
    return output_dict


def dict_filter_bool(kwargs, keep_0=True) -> Optional[dict]:
    if kwargs is None:
        return None

    if keep_0:
        filtered_dict = {k: v for k, v in kwargs.items() if v is not None and v != "" and v is not False}
    else:
        filtered_dict = {k: v for k, v in kwargs.items() if v}

    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def dict_filter_keys(kwargs, keys) -> Optional[dict]:
    filtered_dict = {k: v for k, v in kwargs.items() if k not in keys}
    if len(filtered_dict) == 0:
        return None
    return filtered_dict


def dumbcopy(d):
    return {i: j.copy() if type(j) == dict else j for i, j in d.items()}


def filter_namespace(args, config_opts) -> Optional[Dict]:
    return dict_filter_bool({k: v for k, v in args.__dict__.items() if k in config_opts})
