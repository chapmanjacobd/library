import logging
from subprocess import PIPE, run
import sys
from IPython.core import ultratb


# sys.excepthook = ultratb.FormattedTB(mode="Context", color_scheme="Neutral", call_pdb=1)


def cmd(command, strict=True):
    log = logging.getLogger()
    r = run(command, capture_output=True, text=True, shell=True)
    log.debug(r.args)
    if len(r.stdout.strip()) > 0:
        log.info(r.stdout.strip())
    if len(r.stderr.strip()) > 0:
        log.error(r.stderr.strip())
    if r.returncode != 0:
        log.debug(f"ERROR {r.returncode}")
        if strict:
            raise Exception(r.returncode)
    return r
