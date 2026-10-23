import os, select, shlex, socketserver, subprocess, threading
from contextlib import suppress
from pathlib import Path

from library.utils import consts
from library.utils.log_utils import log


def _print_remote_output(text, is_success, quiet, error_verbosity, ignore_regexps):
    if ignore_regexps is not None:
        text = "\n".join(line for line in text.splitlines() if not any(pattern.match(line) for pattern in ignore_regexps))

    text = text.strip()
    if text:
        if quiet and is_success:
            log.debug(text)
        elif consts.PYTEST_RUNNING:
            log.warning(text)
        elif error_verbosity == 0:
            log.debug(text)
        elif error_verbosity == 1:
            log.info(text)
        else:
            log.warning(text)
    return text


def _copy_remote_files(ssh, command, local_files):
    log.debug("Copying %s files to remote", len(local_files))
    with ssh.open_sftp() as sftp:
        tempdir = ssh_tempdir(ssh) or "."
        library_dir = os.path.join(tempdir, "library_cmd_files")
        cmd(ssh, "mkdir", "-p", library_dir)

        remote_command = list(command)
        for file_path in local_files:
            remote_temp_file = os.path.join(library_dir, Path(file_path).name)
            sftp.put(file_path, remote_temp_file)
            remote_command = [remote_temp_file if item == file_path else item for item in remote_command]
    return remote_command, library_dir


def _cleanup_remote_files(ssh, local_files, library_dir):
    if not local_files:
        return
    with ssh.open_sftp() as sftp:
        for file_path in local_files:
            remote_temp_file = os.path.join(library_dir, Path(file_path).name)
            with suppress(FileNotFoundError):
                sftp.remove(remote_temp_file)


def cmd(
    ssh,  # paramiko.SSHClient
    *command,
    local_files=None,
    cleanup_local_files=True,
    strict=True,
    quiet=True,
    error_verbosity=1,
    ignore_regexps=None,
    cwd=None,
    **kwargs,
) -> subprocess.CompletedProcess:
    library_dir = None
    if local_files:
        command, library_dir = _copy_remote_files(ssh, command, local_files)

    command = shlex.join(str(s) for s in command)
    if cwd:
        command = "cd " + shlex.quote(cwd) + "; " + command
    _stdin, stdout, stderr = ssh.exec_command(command, **kwargs)
    returncode = stdout.channel.recv_exit_status()

    host = getattr(ssh, "host", None)
    if host:  # for logging purposes
        command = f"ssh {host} {command}"

    r = subprocess.CompletedProcess(command, returncode, stdout.read().decode(), stderr.read().decode())

    if cleanup_local_files and local_files:
        _cleanup_remote_files(ssh, local_files, library_dir)

    log.debug(r.args)
    _print_remote_output(r.stdout, r.returncode == 0, quiet, error_verbosity, ignore_regexps)
    _print_remote_output(r.stderr, r.returncode == 0, quiet, error_verbosity, ignore_regexps)
    if r.returncode != 0:
        if error_verbosity == 0:
            log.debug("[%s] exited %s", command, r.returncode)
        elif error_verbosity == 1:
            log.info("[%s] exited %s", command, r.returncode)
        else:
            log.warning("[%s] exited %s", command, r.returncode)

        if strict:
            if error_verbosity <= 1:
                log.error("[%s] exited %s", command, r.returncode)
            r.check_returncode()

    return r


def ssh_tempdir(ssh):
    r = cmd(ssh, "sh", "-c", "echo $XDG_RUNTIME_DIR")
    tempdir = r.stdout.strip()
    if tempdir:
        return tempdir

    r = cmd(ssh, "python3", "-c", "import tempfile; print(tempfile.gettempdir())")
    tempdir = r.stdout.strip()
    if tempdir:
        return tempdir
    return None


class PortForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class PortForwardHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel(  # type: ignore
                "direct-tcpip", (self.chain_host, self.chain_port), self.request.getpeername()  # type: ignore
            )
        except Exception as excinfo:
            log.error("Incoming request to %s:%d failed: %s", self.chain_host, self.chain_port, repr(excinfo))  # type: ignore
            return
        if chan is None:
            log.error("Incoming request to %s:%d was rejected by the SSH server", self.chain_host, self.chain_port)  # type: ignore
            return

        log.debug(
            "Connected! Tunnel open %r -> %r -> %r",
            self.request.getpeername(),
            chan.getpeername(),
            (self.chain_host, self.chain_port),  # type: ignore
        )
        while True:
            r, _w, _x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                self.request.send(data)

        peername = self.request.getpeername()
        chan.close()
        self.request.close()
        log.debug("Tunnel closed from %r", peername)


class SSHForwarder:
    def __init__(self, ssh_client, remote_port, local_port):
        # with SSHForwarder(ssh, remote_port, local_port):

        self.ssh_client = ssh_client
        self.remote_port = remote_port
        self.local_port = local_port
        self.server = None

    def __enter__(self):
        transport = self.ssh_client.get_transport()
        if not transport:
            raise ConnectionError("SSH transport is not available")

        class SubHandler(PortForwardHandler):
            chain_host = "localhost"
            chain_port = self.remote_port
            ssh_transport = transport

        self.server = PortForwardServer(("", self.local_port), SubHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        log.debug("Port forwarding %s to localhost:%s started", self.remote_port, self.local_port)

    def __exit__(self, exc_type, exc_value, traceback):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
