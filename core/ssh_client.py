"""SSH/SFTP client wrapper using paramiko."""

import os
import stat
import subprocess
import threading
from datetime import datetime

import paramiko


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


class SSHClient:
    """Wraps paramiko SSH + SFTP for all remote file operations."""

    def __init__(self):
        self._ssh: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._connected = False
        self._host = ""
        self._port = 22
        self._username = ""
        self._cancel_flag = False

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def username(self) -> str:
        return self._username

    @property
    def label(self) -> str:
        return f"{self._username}@{self._host}:{self._port}" if self._connected else "Not connected"

    def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        key_file: str | None = None,
        key_passphrase: str | None = None,
    ) -> None:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs: dict = {
            "hostname": host,
            "port": int(port),
            "username": username,
            "timeout": 15,
            "banner_timeout": 15,
            "auth_timeout": 15,
        }

        if key_file and key_file.strip():
            pkey = self._load_key(key_file.strip(), key_passphrase)
            kwargs["pkey"] = pkey
            if password:
                kwargs["password"] = password
        elif password:
            kwargs["password"] = password
        else:
            kwargs["look_for_keys"] = True
            kwargs["allow_agent"] = True

        ssh.connect(**kwargs)
        self._ssh = ssh
        self._sftp = ssh.open_sftp()
        self._connected = True
        self._host = host
        self._port = int(port)
        self._username = username

    def _load_key(self, path: str, passphrase: str | None):
        path = os.path.expanduser(path)
        pp = passphrase.encode() if passphrase else None
        for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                return cls.from_private_key_file(path, password=pp)
            except paramiko.PasswordRequiredException:
                raise ValueError(f"Key '{path}' requires a passphrase.")
            except Exception:
                continue
        raise ValueError(f"Could not load private key from '{path}'.")

    def disconnect(self) -> None:
        for obj in (self._sftp, self._ssh):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self._sftp = None
        self._ssh = None
        self._connected = False

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def list_directory(self, path: str) -> list[dict]:
        """Return sorted list of entry dicts for the remote path."""
        try:
            attrs = self._sftp.listdir_attr(path)
        except Exception as exc:
            raise RuntimeError(f"Cannot list '{path}': {exc}") from exc

        entries = []
        for a in attrs:
            is_dir = bool(a.st_mode and stat.S_ISDIR(a.st_mode))
            modified = None
            if a.st_mtime:
                try:
                    modified = datetime.fromtimestamp(a.st_mtime)
                except Exception:
                    pass
            full = path.rstrip("/") + "/" + a.filename
            entries.append(
                {
                    "name": a.filename,
                    "path": full,
                    "is_dir": is_dir,
                    "size": a.st_size or 0,
                    "modified": modified,
                    "permissions": oct(stat.S_IMODE(a.st_mode)) if a.st_mode else "",
                }
            )

        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return entries

    # ------------------------------------------------------------------
    # File transfers
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        self._cancel_flag = True

    def upload(self, local_path: str, remote_path: str, progress=None) -> None:
        self._cancel_flag = False

        def cb(done, total):
            if self._cancel_flag:
                raise InterruptedError("Cancelled")
            if progress:
                progress(done, total)

        self._sftp.put(local_path, remote_path, callback=cb)

    def download(self, remote_path: str, local_path: str, progress=None) -> None:
        self._cancel_flag = False

        def cb(done, total):
            if self._cancel_flag:
                raise InterruptedError("Cancelled")
            if progress:
                progress(done, total)

        self._sftp.get(remote_path, local_path, callback=cb)

    def upload_tree(self, local_path: str, remote_dir: str, state: dict, progress=None) -> None:
        """Recursively upload a local file or directory."""
        name = os.path.basename(local_path)
        if os.path.isdir(local_path):
            remote_sub = remote_dir.rstrip("/") + "/" + name
            try:
                self._sftp.mkdir(remote_sub)
            except Exception:
                pass
            for item in sorted(os.scandir(local_path), key=lambda i: (not i.is_dir(), i.name)):
                self.upload_tree(item.path, remote_sub, state, progress)
        else:
            state["current_file"] = name
            state["file_progress"] = 0
            state["file_total"] = os.path.getsize(local_path)
            remote_path = remote_dir.rstrip("/") + "/" + name
            self.upload(local_path, remote_path, progress)

    def download_tree(self, remote_path: str, local_dir: str, is_dir: bool, state: dict, progress=None) -> None:
        """Recursively download a remote file or directory."""
        name = remote_path.rstrip("/").split("/")[-1]
        if is_dir:
            local_sub = os.path.join(local_dir, name)
            os.makedirs(local_sub, exist_ok=True)
            for entry in self.list_directory(remote_path):
                self.download_tree(entry["path"], local_sub, entry["is_dir"], state, progress)
        else:
            state["current_file"] = name
            state["file_progress"] = 0
            state["file_total"] = 0
            local_path = os.path.join(local_dir, name)
            self.download(remote_path, local_path, progress)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def mkdir(self, path: str) -> None:
        self._sftp.mkdir(path)

    def remove_file(self, path: str) -> None:
        self._sftp.remove(path)

    def remove_dir(self, path: str) -> None:
        for a in self._sftp.listdir_attr(path):
            sub = path.rstrip("/") + "/" + a.filename
            if stat.S_ISDIR(a.st_mode):
                self.remove_dir(sub)
            else:
                self._sftp.remove(sub)
        self._sftp.rmdir(path)

    def rename(self, old: str, new: str) -> None:
        self._sftp.rename(old, new)

    def create_file(self, path: str) -> None:
        with self._sftp.file(path, "w") as f:
            f.write("")

    def read_file(self, path: str) -> bytes:
        with self._sftp.file(path, "rb") as f:
            return f.read()

    def write_file(self, path: str, data: bytes) -> None:
        with self._sftp.file(path, "wb") as f:
            f.write(data)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def get_home_dir(self) -> str:
        try:
            _, out, _ = self._ssh.exec_command("echo $HOME", timeout=5)
            home = out.read().decode().strip()
            return home or "/"
        except Exception:
            return "/"

    def file_exists(self, path: str) -> bool:
        """Return True if the remote path exists."""
        try:
            self._sftp.stat(path)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def exec_command(self, cmd: str) -> tuple[str, str]:
        _, out, err = self._ssh.exec_command(cmd, timeout=15)
        return out.read().decode(), err.read().decode()

    def start_keepalive(self, interval: int = 30) -> None:
        """Send a null SSH packet every `interval` seconds to keep alive."""
        import time

        def _ka():
            while self._connected:
                time.sleep(interval)
                if not self._connected:
                    break
                try:
                    transport = self._ssh.get_transport()
                    if transport and transport.is_active():
                        transport.send_ignore()
                    else:
                        self._connected = False
                except Exception:
                    self._connected = False
                    break

        threading.Thread(target=_ka, daemon=True, name="ssh-keepalive").start()

    def open_terminal(self) -> None:
        """Open a terminal with an SSH session to the remote host."""
        import sys
        cmd = f"ssh -p {self._port} {self._username}@{self._host}"
        if sys.platform == "darwin":
            script = (
                'tell application "Terminal" to activate\n'
                f'tell application "Terminal" to do script "{cmd}"'
            )
            subprocess.Popen(["osascript", "-e", script])
        elif sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", cmd])
        else:
            import shutil
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                if shutil.which(term):
                    if term == "gnome-terminal":
                        subprocess.Popen([term, "--", "bash", "-c", cmd])
                    else:
                        subprocess.Popen([term, "-e", cmd])
                    break
