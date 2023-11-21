import argparse, logging, os, sys
from functools import wraps
from timeit import default_timer

from IPython.core import ultratb
from IPython.terminal import debugger

sys.breakpointhook = debugger.set_trace


def clamp_index(arr, idx):
    return arr[min(max(idx, 0), len(arr) - 1)]


def run_once(f):  # noqa: ANN201
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not f.has_run:
            result = f(*args, **kwargs)
            f.has_run = True
            return result
        return None

    f.has_run = False
    return wrapper


@run_once
def argparse_log() -> logging.Logger:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args, _unknown = parser.parse_known_args()

    try:
        if args.verbose > 0 and os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno()):
            sys.excepthook = ultratb.FormattedTB(
                mode="Verbose" if args.verbose > 1 else "Context",
                color_scheme="Neutral",
                call_pdb=True,
                debugger_cls=debugger.TerminalPdb,
            )
    except Exception:
        pass

    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]

    if args.verbose > 3 or args.verbose == 0:
        logging.root.handlers = []  # clear any existing handlers
        logging.basicConfig(
            level=clamp_index(log_levels, args.verbose),
            format="%(message)s",
        )
    else:
        logging.basicConfig(format="%(message)s")

    logger = logging.getLogger("library")
    logger.setLevel(clamp_index(log_levels, args.verbose))
    return logger


log = argparse_log()


class Timer:
    def __init__(self):
        self.reset()

    def reset(self):
        self.start_time = default_timer()

    def elapsed(self):
        if not hasattr(self, "start_time"):
            raise RuntimeError("Timer has not been started.")
        end_time = default_timer()
        elapsed_time = end_time - self.start_time
        self.reset()
        return f"{elapsed_time:.4f}"
