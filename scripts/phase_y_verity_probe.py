#!/usr/bin/env python3
"""Reproducible fs-verity capability probe for TraceJIT Phase Y.

Answers, on the machine that runs it, the only question that decides whether a
kernel-verified content guard can exist at all:

    can this kernel, on this filesystem, on a file this caller owns, produce a
    kernel-enforced fs-verity file digest that survives a write attempt?

Every step is a real syscall against a disposable file under a temporary
directory. Nothing outside that directory is created, modified or inspected
beyond read-only metadata (/proc, /sys, /dev listings). No user-owned file and
no system executable is ever touched, and fs-verity is never enabled on
anything but the probe's own temporary file.

Exit status is 0 whenever the probe itself ran, including when fs-verity is
unsupported: "unsupported" is a valid, useful answer and not an error.

Usage:
    python3 scripts/phase_y_verity_probe.py [--json-out PATH] [--file-size BYTES]

With --json-out the probe writes its JSON report to PATH as well as stdout.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import json
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time

# --- ioctl definitions, from include/uapi/linux/fsverity.h ------------------

FS_VERITY_HASH_ALG_SHA256 = 1
FS_VERITY_HASH_ALG_SHA512 = 2
FS_VERITY_FL = 0x00100000  # FS_IOC_GETFLAGS flag bit
STATX_ATTR_VERITY = 0x00100000  # statx mask/attribute bit

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _ioc(direction: int, typ: str, nr: int, size: int) -> int:
    return (
        (direction << _IOC_DIRSHIFT)
        | (ord(typ) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


def _ior(typ: str, nr: int, size: int) -> int:
    return _ioc(_IOC_READ, typ, nr, size)


def _iow(typ: str, nr: int, size: int) -> int:
    return _ioc(_IOC_WRITE, typ, nr, size)


def _iowr(typ: str, nr: int, size: int) -> int:
    return _ioc(_IOC_READ | _IOC_WRITE, typ, nr, size)


# struct fsverity_enable_arg is 128 bytes on x86_64 (4x u32, u64, 2x u32, u64,
# then u64 __reserved2[11]).
FSVERITY_ENABLE_ARG_SIZE = 128
# struct fsverity_digest is two u16 plus a flexible array, so _IOC_SIZE is 4.
FSVERITY_DIGEST_HEADER_SIZE = 4

FS_IOC_GETFLAGS = _ior("f", 1, 8)  # long
FS_IOC_ENABLE_VERITY = _iow("f", 133, FSVERITY_ENABLE_ARG_SIZE)
FS_IOC_MEASURE_VERITY = _iowr("f", 134, FSVERITY_DIGEST_HEADER_SIZE)

# Documented failures meaning "fs-verity cannot answer here", as opposed to a
# real error. See Documentation/filesystems/fsverity.rst.
UNAVAILABLE_ERRNOS = {
    errno.ENODATA: "ENODATA (file is not a verity file)",
    errno.ENOTTY: "ENOTTY (filesystem does not implement fs-verity)",
    errno.EOPNOTSUPP: "EOPNOTSUPP (kernel or superblock has no fs-verity)",
    errno.ENOPKG: "ENOPKG (algorithm not built into this kernel)",
    errno.EINVAL: "EINVAL (unsupported argument)",
    errno.EPERM: "EPERM (append-only, or a signature is required)",
    errno.EROFS: "EROFS (filesystem is read-only)",
    errno.EACCES: "EACCES (no write access to enable verity)",
    errno.ETXTBSY: "ETXTBSY (another writer is open)",
    errno.EEXIST: "EEXIST (verity is already enabled)",
    errno.ENOSYS: "ENOSYS (no ioctl support)",
}


class IoctlError(OSError):
    pass


def _ioctl_arg(fd: int, request: int, arg: bytes) -> int:
    """Run an ioctl with a mutable byte buffer, raising OSError with the errno."""
    try:
        fcntl.ioctl(fd, request, arg, True)
    except OSError as error:
        raise IoctlError(error.errno, error.strerror) from None
    return 0


def measure_verity(fd: int) -> dict:
    """FS_IOC_MEASURE_VERITY on an open descriptor.

    Returns {"state": "measured", "algorithm": int, "digest": hex} or
    {"state": "unavailable"|"failed", "errno": int, "detail": str}.
    """
    buffer = bytearray(FSVERITY_DIGEST_HEADER_SIZE + 64)
    # digest_size is an input/output field: bytes allocated for digest[].
    struct.pack_into("<H", buffer, 2, 64)
    try:
        fcntl.ioctl(fd, FS_IOC_MEASURE_VERITY, buffer, True)
    except OSError as error:
        code = error.errno
        state = "unavailable" if code in UNAVAILABLE_ERRNOS else "failed"
        return {"state": state, "errno": code, "detail": UNAVAILABLE_ERRNOS.get(code, error.strerror or "")}
    algorithm, digest_size = struct.unpack_from("<HH", buffer, 0)
    if digest_size > 64:
        return {"state": "malformed", "errno": 0, "detail": f"digest_size {digest_size} exceeds the 64-byte buffer"}
    digest = bytes(buffer[FSVERITY_DIGEST_HEADER_SIZE : FSVERITY_DIGEST_HEADER_SIZE + digest_size])
    return {"state": "measured", "algorithm": algorithm, "digest": digest.hex(), "digest_size": digest_size}


def enable_verity(fd: int, algorithm: int = FS_VERITY_HASH_ALG_SHA256, block_size: int = 4096) -> dict:
    """FS_IOC_ENABLE_VERITY with no salt and no built-in signature."""
    arg = bytearray(FSVERITY_ENABLE_ARG_SIZE)
    struct.pack_into("<IIII", arg, 0, 1, algorithm, block_size, 0)  # version=1, salt_size=0
    try:
        fcntl.ioctl(fd, FS_IOC_ENABLE_VERITY, arg, True)
    except OSError as error:
        code = error.errno
        return {
            "state": "unavailable" if code in UNAVAILABLE_ERRNOS else "failed",
            "errno": code,
            "detail": UNAVAILABLE_ERRNOS.get(code, error.strerror or ""),
        }
    return {"state": "enabled"}


def getflags(fd: int) -> dict:
    buffer = bytearray(8)
    try:
        fcntl.ioctl(fd, FS_IOC_GETFLAGS, buffer, True)
    except OSError as error:
        return {"state": "failed", "errno": error.errno, "detail": error.strerror}
    flags = struct.unpack_from("<q", buffer, 0)[0]
    return {"state": "ok", "flags": flags, "verity_flag": bool(flags & FS_VERITY_FL)}


def statx_verity(path: str) -> dict:
    """STATX_ATTR_VERITY via statx(2) when the libc exposes it."""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        statx = libc.statx
    except (OSError, AttributeError):
        return {"state": "unavailable", "detail": "no statx in libc"}
    # struct statx: 0x100 bytes on x86_64; stx_attributes is u64 at offset 0x40.
    buffer = ctypes.create_string_buffer(256)
    STATX_ALL = 0xFFF
    rc = statx(-100, path.encode(), 0x100, STATX_ALL, buffer)  # AT_FDCWD, AT_STATX_SYNC_AS_STAT
    if rc != 0:
        return {"state": "failed", "errno": ctypes.get_errno(), "detail": os.strerror(ctypes.get_errno())}
    attributes = struct.unpack_from("<Q", buffer.raw, 0x40)[0]
    return {"state": "ok", "attributes": attributes, "verity": bool(attributes & STATX_ATTR_VERITY)}


def read_first_line(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()
    except OSError:
        return None


def kernel_config() -> dict:
    """Best-effort CONFIG_FS_VERITY discovery; many images publish no config."""
    candidates = []
    release = platform.release()
    for path in (f"/boot/config-{release}", f"/lib/modules/{release}/config", "/proc/config.gz"):
        if path.endswith(".gz"):
            if os.path.exists(path):
                try:
                    import gzip

                    with gzip.open(path, "rt", errors="replace") as handle:
                        for line in handle:
                            if "FS_VERITY" in line:
                                candidates.append(line.strip())
                except OSError:
                    pass
            continue
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        if "FS_VERITY" in line:
                            candidates.append(line.strip())
            except OSError:
                pass
    if not candidates:
        return {"published": False, "entries": [], "detail": "no readable kernel config"}
    return {"published": True, "entries": candidates}


def mount_info(path: str) -> dict:
    """Filesystem type and mount options for the filesystem holding `path`."""
    target = os.path.realpath(path)
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as handle:
            best = None
            for line in handle:
                fields = line.split()
                if len(fields) < 5:
                    continue
                mount_point = fields[4]
                if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
                    if best is None or len(mount_point) > len(best[0]):
                        best = (mount_point, fields)
            if best is None:
                return {"state": "unknown"}
            mount_point, fields = best
            options = fields[5] if len(fields) > 5 else ""
            separator = fields.index("-") if "-" in fields else None
            fs_type = fields[separator + 1] if separator is not None else "?"
            super_options = fields[separator + 3] if separator is not None and len(fields) > separator + 3 else ""
            return {
                "state": "ok",
                "mount_point": mount_point,
                "fs_type": fs_type,
                "options": options,
                "super_options": super_options,
            }
    except OSError as error:
        return {"state": "failed", "detail": str(error)}


def process_environment() -> dict:
    report = {
        "uid": os.getuid(),
        "euid": os.geteuid(),
        "gid": os.getgid(),
        "groups": sorted(os.getgroups()),
    }
    status = "/proc/self/status"
    try:
        with open(status, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(("CapEff:", "CapBnd:", "NoNewPrivs:")):
                    key, _, value = line.partition(":")
                    report[key.strip().lower()] = value.strip()
    except OSError:
        pass
    capability_names = {
        1: "CAP_DAC_OVERRIDE",
        4: "CAP_FOWNER",
        9: "CAP_LINUX_IMMUTABLE",
        21: "CAP_SYS_ADMIN",
    }
    try:
        effective = int(report.get("capeff", "0"), 16)
        report["effective_named"] = [name for bit, name in capability_names.items() if effective & (1 << bit)]
        # fs-verity enable needs write access to the file: CAP_DAC_OVERRIDE or CAP_FOWNER
        # substitutes for ownership; the filesystem feature needs CAP_SYS_ADMIN once.
        report["can_override_file_access"] = bool(effective & ((1 << 1) | (1 << 4)))
        report["has_cap_sys_admin"] = bool(effective & (1 << 21))
        report["has_cap_linux_immutable"] = bool(effective & (1 << 9))
    except ValueError:
        pass
    report["unprivileged_userns_clone"] = read_first_line("/proc/sys/kernel/unprivileged_userns_clone")
    report["max_user_namespaces"] = read_first_line("/proc/sys/user/max_user_namespaces")
    report["kvm_device"] = os.path.exists("/dev/kvm")
    report["kvm_usable"] = os.access("/dev/kvm", os.R_OK | os.W_OK) if os.path.exists("/dev/kvm") else False
    report["tools"] = {tool: shutil.which(tool) for tool in ("qemu-system-x86_64", "firecracker", "mke2fs", "tune2fs", "fsverity", "docker")}
    return report


def fs_verity_util_available() -> dict:
    tool = shutil.which("fsverity")
    return {"available": tool is not None, "path": tool}


def hash_cost(path: str, rounds: int = 20) -> dict:
    """Baseline: cost of reading and hashing the whole file (blake3 when importable)."""
    try:
        import hashlib

        hasher_name = "sha256"
        new_hash = hashlib.sha256
    except ImportError:  # pragma: no cover - hashlib is always present
        return {"state": "unavailable"}
    size = os.path.getsize(path)
    started = time.perf_counter()
    for _ in range(rounds):
        digest = new_hash()
        with open(path, "rb", buffering=0) as handle:
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
    elapsed = time.perf_counter() - started
    return {
        "state": "ok",
        "algorithm": hasher_name,
        "rounds": rounds,
        "bytes": size,
        "mean_ns": (elapsed / rounds) * 1e9,
        "bytes_per_second": (size * rounds) / elapsed if elapsed else 0,
    }


def measure_cost(fd: int, rounds: int = 1000) -> dict:
    """Cost of one FS_IOC_MEASURE_VERITY attempt on `fd`, whatever it returns."""
    buffer = bytearray(FSVERITY_DIGEST_HEADER_SIZE + 64)
    struct.pack_into("<H", buffer, 2, 64)
    started = time.perf_counter()
    outcomes = {}
    for _ in range(rounds):
        try:
            fcntl.ioctl(fd, FS_IOC_MEASURE_VERITY, buffer, True)
            key = "measured"
        except OSError as error:
            key = f"errno {error.errno}"
        outcomes[key] = outcomes.get(key, 0) + 1
    elapsed = time.perf_counter() - started
    return {"rounds": rounds, "mean_ns": (elapsed / rounds) * 1e9, "outcomes": outcomes}


def probe(directory: str, file_size: int) -> dict:
    """Full verity lifecycle against a disposable file in `directory`."""
    result: dict = {"directory": directory, "file_size": file_size}
    path = os.path.join(directory, "verity-probe.bin")
    with open(path, "wb") as handle:
        handle.write(b"A" * file_size)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o755)

    report: dict = {}
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as error:
        return {"state": "failed", "detail": f"open O_RDONLY: {error}"}
    try:
        report["getflags_before"] = getflags(fd)
        report["statx_before"] = statx_verity(path)
        report["measure_before"] = measure_verity(fd)
        report["measure_cost_unsupported"] = measure_cost(fd, rounds=500)
        report["hash_cost"] = hash_cost(path, rounds=10)
        report["enable"] = enable_verity(fd)
        if report["enable"]["state"] == "enabled":
            report["measure_after"] = measure_verity(fd)
            report["statx_after"] = statx_verity(path)
            report["getflags_after"] = getflags(fd)
            report["measure_cost_verity"] = measure_cost(fd, rounds=1000)
            # Write attempts: in place, truncate, re-open for writing.
            report["write_in_place"] = _attempt(lambda: os.pwrite(fd, b"X", 0))
            report["truncate"] = _attempt(lambda: os.ftruncate(fd, 0))
            report["open_for_write"] = _attempt(lambda: os.close(os.open(path, os.O_WRONLY)))
            os.close(fd)
            fd = os.open(path, os.O_RDONLY)
            report["rename"] = _attempt(lambda: (os.rename(path, path + ".moved"), os.rename(path + ".moved", path))[0])
            report["hardlink"] = _attempt(lambda: os.link(path, path + ".link"))
            report["symlink"] = _attempt(lambda: os.symlink(path, path + ".symlink"))
            report["chmod"] = _attempt(lambda: os.chmod(path, 0o700))
            # Pathname replacement: a *different* inode at the same name.
            report["pathname_replacement"] = _pathname_replacement(path, report["measure_after"]["digest"])
            report["delete_and_recreate"] = _delete_and_recreate(path, report["measure_after"]["digest"])
            report["copy_loses_verity"] = _copy_loses_verity(directory, path)
            report["measure_after_replacement"] = measure_verity(os.open(path, os.O_RDONLY))
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    for suffix in (".moved", ".link", ".symlink", ".copy"):
        try:
            os.unlink(path + suffix)
        except OSError:
            pass
    try:
        os.unlink(path)
    except OSError:
        pass
    result.update(report)
    enabled = report.get("enable", {}).get("state") == "enabled"
    result["state"] = "verity-enabled" if enabled else "verity-unavailable"
    return result


def _attempt(fn) -> dict:
    try:
        fn()
        return {"state": "succeeded"}
    except OSError as error:
        return {"state": "refused", "errno": error.errno, "detail": error.strerror}


def _pathname_replacement(path: str, expected_digest: str) -> dict:
    """Replace the path with a fresh, non-verity inode of the same size."""
    backup = path + ".orig"
    size = os.path.getsize(path)
    try:
        os.rename(path, backup)
        with open(path, "wb") as handle:
            handle.write(b"B" * size)
        fd = os.open(path, os.O_RDONLY)
        try:
            measurement = measure_verity(fd)
        finally:
            os.close(fd)
        os.unlink(path)
        os.rename(backup, path)
        return {
            "state": "replaced",
            "measurement_of_replacement": measurement,
            "detected": measurement.get("state") != "measured" or measurement.get("digest") != expected_digest,
        }
    except OSError as error:
        try:
            if os.path.exists(backup) and not os.path.exists(path):
                os.rename(backup, path)
        except OSError:
            pass
        return {"state": "failed", "errno": error.errno, "detail": error.strerror}


def _delete_and_recreate(path: str, expected_digest: str) -> dict:
    backup = path + ".orig"
    size = os.path.getsize(path)
    try:
        os.rename(path, backup)
    except OSError as error:
        return {"state": "failed", "detail": str(error)}
    try:
        with open(path, "wb") as handle:
            handle.write(b"C" * size)
        fd = os.open(path, os.O_RDONLY)
        try:
            measurement = measure_verity(fd)
        finally:
            os.close(fd)
        return {
            "state": "recreated",
            "measurement": measurement,
            "detected": measurement.get("state") != "measured" or measurement.get("digest") != expected_digest,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        try:
            os.rename(backup, path)
        except OSError:
            pass


def _copy_loses_verity(directory: str, path: str) -> dict:
    copy = path + ".copy"
    try:
        shutil.copyfile(path, copy)
        fd = os.open(copy, os.O_RDONLY)
        try:
            return {"state": "copied", "measurement": measure_verity(fd)}
        finally:
            os.close(fd)
    except OSError as error:
        return {"state": "failed", "detail": str(error)}
    finally:
        try:
            os.unlink(copy)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json-out", help="also write the report to this path")
    parser.add_argument("--file-size", type=int, default=1 << 20, help="probe file size in bytes")
    parser.add_argument("--directory", help="directory to place the disposable probe file in")
    args = parser.parse_args(argv)

    report: dict = {
        "probe": "tracejit-phase-y-verity",
        "host": {
            "platform": platform.platform(),
            "kernel_release": platform.release(),
            "kernel_version": platform.version(),
            "machine": platform.machine(),
        },
        "os_release": _os_release(),
        "kernel_config": kernel_config(),
        "process": process_environment(),
        "fsverity_util": fs_verity_util_available(),
        "ioctl_numbers": {
            "FS_IOC_GETFLAGS": hex(FS_IOC_GETFLAGS),
            "FS_IOC_ENABLE_VERITY": hex(FS_IOC_ENABLE_VERITY),
            "FS_IOC_MEASURE_VERITY": hex(FS_IOC_MEASURE_VERITY),
        },
    }

    with tempfile.TemporaryDirectory(prefix="tracejit-verity-probe-") as directory:
        if args.directory:
            directory = args.directory  # type: ignore[assignment]
        report["mount"] = mount_info(directory)
        report["lifecycle"] = probe(directory, args.file_size)

    report["verdict"] = _verdict(report)
    text = json.dumps(report, indent=2, sort_keys=False)
    print(text)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0


def _os_release() -> dict:
    values: dict[str, str] = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, separator, value = line.strip().partition("=")
                if separator:
                    values[key] = value.strip('"')
    except OSError:
        pass
    return values


def _verdict(report: dict) -> dict:
    lifecycle = report["lifecycle"]
    enabled = lifecycle.get("state") == "verity-enabled"
    config = report["kernel_config"]
    configured = None
    if config.get("published"):
        entries = " ".join(config.get("entries", []))
        configured = "CONFIG_FS_VERITY=y" in entries or "CONFIG_FS_VERITY=m" in entries
    return {
        "fs_verity_supported_here": enabled,
        "kernel_configured_for_fs_verity": configured,
        "kernel_measurement_available": lifecycle.get("measure_before", {}).get("state") == "measured",
        "enable_errno": lifecycle.get("enable", {}).get("detail"),
        "conclusion": (
            "fs-verity is available on this filesystem: the kernel produced a digest and enforced it"
            if enabled
            else "fs-verity is NOT available here: a kernel-verified content guard cannot be tested or used on this host"
        ),
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
