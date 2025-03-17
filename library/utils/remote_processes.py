import os, select, shlex, socketserver, subprocess, threading
from contextlib import suppress
from pathlib import Path

from library.utils import consts, remote_processes
from library.utils.log_utils import log


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

    if local_files:
        log.debug("Copying %s files to remote", len(local_files))
        with ssh.open_sftp() as sftp:
            sftp = ssh.open_sftp()

            tempdir = remote_processes.ssh_tempdir(ssh) or "."
            library_dir = os.path.join(tempdir, "library_cmd_files")
            r = remote_processes.cmd(ssh, "mkdir", "-p", library_dir)

            for file in local_files:
                remote_temp_file = os.path.join(library_dir, Path(file).name)
                sftp.put(file, remote_temp_file)
                command = [remote_temp_file if s == file else s for s in command]

    command = shlex.join(str(s) for s in command)
    if cwd:
        command = "cd " + shlex.quote(cwd) + "; " + command
    _stdin, stdout, stderr = ssh.exec_command(command, **kwargs)
    returncode = stdout.channel.recv_exit_status()

    host = getattr(ssh, "host", None)
    if host:  # for logging purposes
        command = " ".join(["ssh", host, command])

    r = subprocess.CompletedProcess(command, returncode, stdout.read().decode(), stderr.read().decode())

    if cleanup_local_files and local_files:
        with ssh.open_sftp() as sftp:
            for file in local_files:
                remote_temp_file = os.path.join(library_dir, Path(file).name)
                with suppress(FileNotFoundError):
                    sftp.remove(remote_temp_file)

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
            if error_verbosity <= 1:
                log.error("[%s] exited %s", command, r.returncode)
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


class PortForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class PortForwardHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel(  # type: ignore
                "direct-tcpip", (self.chain_host, self.chain_port), self.request.getpeername()  # type: ignore
            )
        except Exception as e:
            log.error("Incoming request to %s:%d failed: %s", self.chain_host, self.chain_port, repr(e))  # type: ignore
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
            r, w, x = select.select([self.request, chan], [], [])
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
            raise Exception("SSH transport is not available")

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
