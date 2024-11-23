import shlex, subprocess

import paramiko

from xklb.utils import consts, remote_processes
from xklb.utils.log_utils import log


def cmd(
    ssh: paramiko.SSHClient, *command, strict=True, quiet=True, error_verbosity=1, ignore_regexps=None, **kwargs
) -> subprocess.CompletedProcess:
    def print_std(s, is_success):
        if ignore_regexps is not None:
            s = "\n".join(line for line in s.splitlines() if not any(r.match(line) for r in ignore_regexps))

        s = s.strip()
        if s:
            if quiet and is_success:
                log.debug(s)
            elif consts.PYTEST_RUNNING:
                log.warning(s)
            elif error_verbosity == 0:
                log.debug(s)
            elif error_verbosity == 1:
                log.info(s)
            else:
                log.warning(s)
        return s

    command = shlex.join(str(s) for s in command)
    _stdin, stdout, stderr = ssh.exec_command(command, **kwargs)
    returncode = stdout.channel.recv_exit_status()

    r = subprocess.CompletedProcess(command, returncode, stdout.read().decode(), stderr.read().decode())

    log.debug(r.args)
    print_std(r.stdout, r.returncode == 0)
    print_std(r.stderr, r.returncode == 0)
    if r.returncode != 0:
        if error_verbosity == 0:
            log.debug("[%s] exited %s", command, r.returncode)
        elif error_verbosity == 1:
            log.info("[%s] exited %s", command, r.returncode)
        else:
            log.warning("[%s] exited %s", command, r.returncode)

        if strict:
            r.check_returncode()

    return r


def ssh_tempdir(ssh):
    r = remote_processes.cmd(ssh, "sh", "-c", "echo $XDG_RUNTIME_DIR")
    tempdir = r.stdout.strip()
    if tempdir:
        return tempdir

    r = remote_processes.cmd(ssh, "python3", "-c", "import tempfile; print(tempfile.gettempdir())")
    tempdir = r.stdout.strip()
    if tempdir:
        return tempdir
