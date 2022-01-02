import logging
from subprocess import PIPE, run


def cmd(command, **kwargs):
    log = logging.getLogger()
    r = run(
        command, stdout=PIPE, stderr=PIPE, universal_newlines=True, shell=True, **kwargs
    )
    if r.returncode != 0:
        raise Exception(f"ERROR {r.returncode}")
    print(r.stderr.strip())
    return r
