"""Owner-only metadata and advisory locks. Credentials are never opened here."""

import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys


class SwitcherError(Exception):
    """An actionable, redacted error safe for the terminal."""


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value):
        raise SwitcherError("Profile names must start with a lowercase letter and use up to 32 letters, digits, _ or -.")
    return value


def canonical_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise SwitcherError("Use an absolute path without control characters.")
    if path.is_symlink():
        raise SwitcherError("The selected directory must not be a symlink; select its actual path.")
    return Path(os.path.realpath(path))


def outside_git(path):
    if any(os.path.lexists(parent / ".git") for parent in (path, *path.parents)):
        raise SwitcherError("Keep profile homes and private switcher state outside Git working trees.")


def validate_directory(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SwitcherError("The selected directory must belong to you and have mode 0700. Review it, then use chmod 700 explicitly.")
    return info


def validate_file(fd):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_nlink != 1):
        raise SwitcherError("A private state file is unsafe: require an owned regular file, mode 0600, with no hard links.")
    return info


@contextlib.contextmanager
def directory(path, create=False):
    path = canonical_path(path)
    outside_git(path)
    # Parent symlinks are canonicalized; writable ancestors could replace the
    # final path before Codex opens it. Same-user/root attacks are out of scope.
    for ancestor in path.parents:
        if ancestor.exists():
            info = ancestor.stat()
            sticky_root_tmp = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_mode & 0o022 and not sticky_root_tmp:
                raise SwitcherError("A parent directory is writable by other users; choose a private location.")
    if create:
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for item in reversed(missing):
            try:
                os.mkdir(item, 0o700)
            except FileExistsError:
                pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        validate_directory(fd)
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def file_lock(dir_fd, name, exclusive=True, nonblocking=False):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        validate_file(fd)
        mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, mode | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError:
            raise SwitcherError("This profile is busy. Close its wrapped sessions before login, logout or forgetting it.") from None
        yield
    finally:
        os.close(fd)


def read_json(dir_fd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    except FileNotFoundError:
        return {"schema": 1, "profiles": {}}
    try:
        info = validate_file(fd)
        if info.st_size > 65536:
            raise SwitcherError("The profile registry exceeds its size limit.")
        chunks = bytearray()
        while True:
            part = os.read(fd, 65537 - len(chunks))
            if not part:
                break
            chunks.extend(part)
            if len(chunks) > 65536:
                raise SwitcherError("The profile registry exceeds its size limit.")
        try:
            return json.loads(chunks)
        except (ValueError, UnicodeError):
            raise SwitcherError("The profile registry is invalid. Preserve it before repairing it.") from None
    finally:
        os.close(fd)


def atomic_write(dir_fd, name, data):
    if len(data) > 65536:
        raise SwitcherError("Private metadata exceeds its size limit; existing metadata was preserved.")
    temporary = ".write-" + secrets.token_hex(12)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=dir_fd)
    try:
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count == 0:
                raise SwitcherError("Could not complete the private metadata write.")
            view = view[count:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=dir_fd)
        except FileNotFoundError:
            pass


def default_state():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/codex-account-switcher"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and not Path(xdg).is_absolute():
        raise SwitcherError("XDG_DATA_HOME must be an absolute path.")
    return (Path(xdg) if xdg else Path.home() / ".local/share") / "codex-account-switcher"


class Registry:
    def __init__(self, path):
        self.path = canonical_path(path)

    @contextlib.contextmanager
    def transaction(self):
        with directory(self.path, create=True) as root:
            with file_lock(root, "registry.lock"):
                document = read_json(root, "profiles.json")
                if (not isinstance(document, dict) or type(document.get("schema")) is not int or document.get("schema") != 1
                        or not isinstance(document.get("profiles"), dict)
                        or len(document["profiles"]) > 128):
                    raise SwitcherError("Unsupported or invalid profile registry; preserve it before repairing it.")
                for name, profile in document["profiles"].items():
                    self.validate_record(name, profile)
                yield root, document

    def validate_record(self, name, profile):
        label(name)
        if not isinstance(profile, dict) or set(profile) != {"home", "kind", "storage", "device", "inode"}:
            raise SwitcherError("Invalid profile record.")
        if (profile["kind"] not in ("managed", "registered")
                or profile["storage"] not in ("keyring", "file", "inherit")
                or (profile["kind"] == "registered") != (profile["storage"] == "inherit")
                or not isinstance(profile["home"], str)
                or len(profile["home"]) > 4096
                or any(type(profile[k]) is not int or profile[k] < 0 for k in ("device", "inode"))):
            raise SwitcherError("Invalid profile record.")
        path = canonical_path(profile["home"])
        if str(path) != profile["home"]:
            raise SwitcherError("A profile path has changed; preserve its original home before re-registering it.")
        if profile["kind"] == "managed" and path != self.path / "homes" / name:
            raise SwitcherError("A managed profile points outside its assigned home.")

    def profiles(self):
        with self.transaction() as (_, document):
            return document["profiles"].copy()

    def add(self, name, home=None, storage="keyring", allow_plaintext=False):
        label(name)
        if storage not in ("keyring", "file"):
            raise SwitcherError("Choose keyring or file storage.")
        if home is None and storage == "file" and not allow_plaintext:
            raise SwitcherError("File storage leaves credentials in plaintext. Add --allow-plaintext only if you accept that.")
        with self.transaction() as (root, document):
            profiles = document["profiles"]
            if name in profiles:
                raise SwitcherError("That profile name already exists; existing data was preserved.")
            if len(profiles) >= 128:
                raise SwitcherError("At most 128 profiles can be registered.")
            target = canonical_path(home) if home is not None else self.path / "homes" / name
            outside_git(target)
            for profile in profiles.values():
                other = Path(profile["home"])
                if target == other or target in other.parents or other in target.parents:
                    raise SwitcherError("Profile homes must be distinct and cannot contain one another.")
            if home is None:
                with directory(self.path / "homes", create=True) as homes:
                    try:
                        os.mkdir(name, 0o700, dir_fd=homes)
                    except FileExistsError:
                        raise SwitcherError("The new home already exists. It was preserved; inspect it before registering it explicitly.") from None
                with directory(target) as selected:
                    config = (f'cli_auth_credentials_store = "{storage}"\n'
                              'forced_login_method = "chatgpt"\n').encode()
                    atomic_write(selected, "config.toml", config)
                    info = os.fstat(selected)
                kind = "managed"
            else:
                with directory(target) as selected:
                    check_home_files(selected)
                    info = os.fstat(selected)
                kind, storage = "registered", "inherit"
            profiles[name] = {"home": str(target), "kind": kind, "storage": storage,
                              "device": info.st_dev, "inode": info.st_ino}
            atomic_write(root, "profiles.json", json.dumps(document, sort_keys=True).encode())

    @contextlib.contextmanager
    def selected(self, name, exclusive=False):
        label(name)
        # Take the profile lock while registry is locked; after that, unrelated
        # profiles and shared runs can proceed without holding the registry.
        with directory(self.path, create=True) as root:
            with self.transaction() as (_, document):
                profile = document["profiles"].get(name)
                if profile is None:
                    raise SwitcherError("Unknown profile. Use list, create or register first.")
                lock = file_lock(root, name + ".lock", exclusive=exclusive, nonblocking=True)
                lock.__enter__()
            try:
                with directory(profile["home"]) as home:
                    info = os.fstat(home)
                    if (info.st_dev, info.st_ino) != (profile["device"], profile["inode"]):
                        raise SwitcherError("The profile directory was replaced. Inspect it before re-registering it.")
                    check_home_files(home)
                    yield profile
            finally:
                lock.__exit__(None, None, None)

    def forget(self, name):
        label(name)
        with self.transaction() as (root, document):
            if name not in document["profiles"]:
                raise SwitcherError("Unknown profile.")
            with file_lock(root, name + ".lock", nonblocking=True):
                del document["profiles"][name]
                atomic_write(root, "profiles.json", json.dumps(document, sort_keys=True).encode())


def check_home_files(home_fd):
    # Metadata only: native Codex, never this wrapper, opens credential contents.
    for name in ("auth.json", ".credentials.json", "config.toml"):
        try:
            info = os.stat(name, dir_fd=home_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise SwitcherError("A home config/auth file is unsafe. Require owned regular files with mode 0600 and no hard links; existing files were preserved.")
    try:
        secrets_fd = os.open("secrets", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=home_fd)
    except FileNotFoundError:
        return
    try:
        validate_directory(secrets_fd)
        for name in ("codex_auth.age", "local.age", "mcp_oauth.age"):
            try:
                info = os.stat(name, dir_fd=secrets_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise SwitcherError("A native encrypted-secrets file has unsafe ownership, permissions or links; existing files were preserved.")
    finally:
        os.close(secrets_fd)
