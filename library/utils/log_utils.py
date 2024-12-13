import argparse, logging, os, sys
from timeit import default_timer

from IPython.core import ultratb
from IPython.terminal import debugger


def check_stdio():
    try:
        has_stdin = os.getpgrp() == os.tcgetpgrp(sys.stdin.fileno())
        has_stdout = os.getpgrp() == os.tcgetpgrp(sys.stdout.fileno())
    except Exception:
        has_stdin, has_stdout = False, False
    return has_stdin, has_stdout


def clamp_index(arr, idx):
    return arr[min(max(idx, 0), len(arr) - 1)]


def argparse_log() -> logging.Logger:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--no-pdb", action="store_true")
    args, _unknown = parser.parse_known_args()

    has_stdin, has_stdout = check_stdio()

    if args.verbose > 0 and has_stdin and has_stdout:
        sys.breakpointhook = debugger.set_trace
        if not args.no_pdb:
            sys.excepthook = ultratb.FormattedTB(
                mode="Verbose" if args.verbose > 1 else "Context",
                color_scheme="Neutral",
                call_pdb=True,
                debugger_cls=debugger.TerminalPdb,
            )

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


def gen_logging(name, original_generator):
    for x in original_generator:
        if name is not None:
            log.debug(f"{name}: {x}")
        else:
            log.debug(x)
        yield x


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
