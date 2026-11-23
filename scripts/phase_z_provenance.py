#!/usr/bin/env python3
"""Attribute `getrandom` observations to the code that issued them.

This is an *independent* observer. It is not TraceJIT's tracer and shares no code with it: it is a
small ptrace loop that stops every traced task at syscall entry and exit, reads the issuing
instruction pointer, the instruction bytes at that pointer, and the mappings that contain the
pointer and the destination buffer. Its answers are therefore evidence about the tracer, not a
restatement of it.

What it computes, per observation:

  module / offset        which mapped file issued the call, and where inside it
  site bytes             the 16 bytes at the instruction pointer, read from the task's memory
  destination            the buffer, and the mapping permissions that contain it
  shape                  requested length and flags
  classification         `runtime-internal-probe` only when all of the following hold at once:
                           - the caller is a shared library, not the program's own text;
                           - the instruction pointer is in an executable mapping of that library;
                           - the buffer is in a private writable mapping of the same library;
                           - the sequence is `mov $318,%eax; syscall` with a
                             `mov $1,%edx; mov $8,%esi` request before it;
                           - the syscall returned 8.
                         Everything else is `other`.

A stack frame that points into libc is not evidence of anything, and neither is a symbol name, so
neither is used here. The call site is identified by the instructions that will issue the call and
by the mapping that will receive its bytes.

Usage:

  python3 scripts/phase_z_provenance.py --json out.json -- gcc -O2 -c unit.c -o unit.o
  python3 scripts/phase_z_provenance.py --summary -- python3 -c 'import os; os.urandom(1)'
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import signal
import sys
from pathlib import Path

SYS_GETRANDOM = 318

PTRACE_TRACEME = 0
PTRACE_PEEKTEXT = 1
PTRACE_CONT = 7
PTRACE_GETREGS = 12
PTRACE_SYSCALL = 24
PTRACE_SETOPTIONS = 0x4200
PTRACE_GETEVENTMSG = 0x4201
PTRACE_GET_SYSCALL_INFO = 0x420E
SYSCALL_INFO_ENTRY = 1
SYSCALL_INFO_EXIT = 2
PTRACE_O_TRACESYSGOOD = 0x1
PTRACE_O_TRACEFORK = 0x2
PTRACE_O_TRACEVFORK = 0x4
PTRACE_O_TRACECLONE = 0x8
PTRACE_O_TRACEEXEC = 0x10
PTRACE_O_EXITKILL = 0x100000
EVENT_FORK = 1
EVENT_VFORK = 2
EVENT_CLONE = 3
EVENT_EXEC = 4
WALL = 0x40000000

MOV_EDX_NONBLOCK = bytes([0xBA, 0x01, 0x00, 0x00, 0x00])
MOV_ESI_EIGHT = bytes([0xBE, 0x08, 0x00, 0x00, 0x00])
MOV_EAX_GETRANDOM = bytes([0xB8, 0x3E, 0x01, 0x00, 0x00])

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.ptrace.restype = ctypes.c_long
libc.ptrace.argtypes = [
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_void_p,
]


class UserRegs(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "r15", "r14", "r13", "r12", "rbp", "rbx", "r11", "r10", "r9", "r8",
        "rax", "rcx", "rdx", "rsi", "rdi", "orig_rax", "rip", "cs", "eflags",
        "rsp", "ss", "fs_base", "gs_base", "ds", "es", "fs", "gs",
    )]


def ptrace(request: int, pid: int, address: int = 0, data=None) -> int:
    if data is None:
        payload = ctypes.c_void_p(0)
    elif isinstance(data, int):
        payload = ctypes.c_void_p(data)
    else:
        payload = ctypes.cast(data, ctypes.c_void_p)
    result = libc.ptrace(request, pid, ctypes.c_void_p(address), payload)
    if result == -1:
        error = ctypes.get_errno()
        if error:
            raise OSError(error, os.strerror(error))
    return result


class SyscallInfo(ctypes.Structure):
    """`struct ptrace_syscall_info` (kernel 5.3+).

    The kernel states whether this stop is an entry or an exit, so the analyzer never has to infer
    it from `rax` or from counting stops. That inference is exactly the kind of guess this script
    exists to avoid.
    """

    _fields_ = [
        ("op", ctypes.c_ubyte),
        ("pad", ctypes.c_ubyte * 3),
        ("arch", ctypes.c_uint32),
        ("ip", ctypes.c_ulonglong),
        ("sp", ctypes.c_ulonglong),
        ("payload", ctypes.c_ubyte * 64),
    ]

    def entry(self) -> tuple[int, list[int]]:
        number = int.from_bytes(bytes(self.payload[0:8]), "little")
        args = [
            int.from_bytes(bytes(self.payload[8 + index * 8 : 16 + index * 8]), "little")
            for index in range(6)
        ]
        return number, args

    def return_value(self) -> int:
        return int.from_bytes(bytes(self.payload[0:8]), "little", signed=True)


def syscall_info(pid: int) -> SyscallInfo | None:
    info = SyscallInfo()
    if ctypes.sizeof(info) < 88:
        raise SystemExit("SyscallInfo is smaller than struct ptrace_syscall_info")
    result = libc.ptrace(
        PTRACE_GET_SYSCALL_INFO,
        pid,
        ctypes.c_void_p(ctypes.sizeof(info)),
        ctypes.cast(ctypes.byref(info), ctypes.c_void_p),
    )
    if result <= 0:
        return None
    return info


def registers(pid: int) -> UserRegs:
    regs = UserRegs()
    ptrace(PTRACE_GETREGS, pid, 0, ctypes.byref(regs))
    return regs


def read_memory(pid: int, address: int, length: int) -> bytes:
    """Read tracee memory through PEEKTEXT, aligned to words."""
    collected = bytearray()
    at = address
    while len(collected) < length:
        word_address = at & ~0x7
        word = ptrace(PTRACE_PEEKTEXT, pid, word_address)
        raw = (word & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
        skip = at - word_address
        collected += raw[skip : skip + (length - len(collected))]
        at += 8 - skip
    return bytes(collected)


class Mapping:
    def __init__(self, start: int, end: int, offset: int, permissions: str, path: str):
        self.start = start
        self.end = end
        self.offset = offset
        self.permissions = permissions
        self.path = path

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end

    @property
    def base(self) -> int:
        return self.start - self.offset

    def describe(self) -> dict:
        return {
            "path": self.path,
            "start": hex(self.start),
            "end": hex(self.end),
            "offset": hex(self.offset),
            "permissions": self.permissions,
        }


def mappings(pid: int) -> list[Mapping]:
    result = []
    for line in Path(f"/proc/{pid}/maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 5:
            continue
        span, permissions, offset, _device, _inode = fields[:5]
        # An anonymous mapping has no pathname. glibc's tcache key lives in the anonymous tail the
        # loader maps for `.bss`, so an empty path here is the expected case, not a parse failure.
        path = fields[5].strip() if len(fields) > 5 else ""
        start, end = (int(part, 16) for part in span.split("-"))
        result.append(Mapping(start, end, int(offset, 16), permissions, path))
    return result


def find(maps: list[Mapping], address: int) -> Mapping | None:
    return next((mapping for mapping in maps if mapping.contains(address)), None)


def writable_data_contains(library: str, offset: int) -> bool:
    """Whether `offset` falls inside a `PT_LOAD` the library maps writable.

    This is an ELF fact about the file, not a mapping fact about the process: the loader maps the
    writable segment's tail anonymously, so the destination has no pathname of its own.
    """
    try:
        image = Path(library).read_bytes()
    except OSError:
        return False
    if image[:4] != b"\x7fELF" or image[4] != 2 or image[5] != 1:
        return False
    program_offset = int.from_bytes(image[0x20:0x28], "little")
    entry_size = int.from_bytes(image[0x36:0x38], "little")
    entry_count = int.from_bytes(image[0x38:0x3A], "little")
    for index in range(entry_count):
        at = program_offset + index * entry_size
        kind = int.from_bytes(image[at : at + 4], "little")
        flags = int.from_bytes(image[at + 4 : at + 8], "little")
        virtual = int.from_bytes(image[at + 16 : at + 24], "little")
        memory_size = int.from_bytes(image[at + 40 : at + 48], "little")
        if kind == 1 and flags & 0x2 and virtual <= offset < virtual + memory_size:
            return True
    return False


def classify(pid: int, ip: int, buffer_address: int, length: int, flags: int, return_value: int) -> dict:
    maps = mappings(pid)
    code = find(maps, ip)
    buffer = find(maps, buffer_address)
    executable = os.readlink(f"/proc/{pid}/exe")
    site = read_memory(pid, ip - 2, 18)
    observation = {
        "pid": pid,
        "rip": hex(ip),
        "module": code.path if code else None,
        "module_offset": hex(ip - code.base) if code else None,
        "caller_is_program": bool(code and code.path == executable),
        "caller_executable_mapping": bool(code and code.permissions.startswith("r-x")),
        "buffer": hex(buffer_address),
        "buffer_module": (buffer.path or None) if buffer else None,
        "buffer_offset": hex(buffer_address - buffer.base) if buffer else None,
        "buffer_offset_in_caller": hex(buffer_address - code.base) if code else None,
        "buffer_private_writable": bool(buffer and buffer.permissions.startswith("rw") and "s" not in buffer.permissions),
        "destination_in_library_writable_segment": bool(
            code and writable_data_contains(code.path, buffer_address - code.base)
        ),
        "length": length,
        "flags": flags,
        "return_value": return_value,
        "site_bytes": site.hex(),
        "caller_nearest_symbol": nearest_symbol(code.path, ip - code.base) if code and code.path.startswith("/") else None,
    }
    audit_tail = bytes([0x48, 0x8D, 0x5D, 0xD0, 0x48, 0x83, 0xF8, 0x08])
    tail = site[2 : 2 + len(audit_tail)]
    shape = site[:2] == b"\x0f\x05" and tail == audit_tail[: len(tail)]
    approved = (
        observation["module"] is not None
        and not observation["caller_is_program"]
        and observation["caller_executable_mapping"]
        and observation["buffer_private_writable"]
        and observation["destination_in_library_writable_segment"]
        and observation["length"] == 8
        and observation["flags"] == 1
        and return_value == 8
        and shape
    )
    observation["classification"] = "runtime-internal-probe" if approved else "other"
    observation["admission_checks"] = {
        "shared_library_caller": bool(observation["module"] and not observation["caller_is_program"]),
        "executable_call_site": observation["caller_executable_mapping"],
        "destination_in_library_writable_segment": observation[
            "destination_in_library_writable_segment"
        ],
        "private_writable_destination": observation["buffer_private_writable"],
        "eight_nonblocking_bytes": observation["length"] == 8 and observation["flags"] == 1,
        "audited_instruction_tail": shape,
        "full_read": return_value == 8,
    }
    return observation


_symbol_cache: dict[str, list[tuple[int, str]]] = {}


def nearest_symbol(path: str, offset: int) -> str | None:
    """Nearest dynamic symbol, printed for orientation only - never used for admission."""
    import subprocess

    if path not in _symbol_cache:
        output = subprocess.run(
            ["nm", "-D", "--defined-only", path], capture_output=True, text=True, check=False
        ).stdout
        symbols = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) == 3:
                try:
                    symbols.append((int(parts[0], 16), parts[2]))
                except ValueError:
                    pass
        _symbol_cache[path] = sorted(symbols)
    symbols = _symbol_cache[path]
    name = None
    for value, symbol in symbols:
        if value > offset:
            break
        name = (value, symbol)
    if name is None:
        return None
    return f"{name[1]}+{offset - name[0]:#x}"


def run(command: list[str]) -> dict:
    child = os.fork()
    if child == 0:
        try:
            ptrace(PTRACE_TRACEME, 0)
            os.kill(os.getpid(), signal.SIGSTOP)
            os.execvp(command[0], command)
        except BaseException:
            os._exit(127)
    _, status = os.waitpid(child, 0)
    if not os.WIFSTOPPED(status):
        raise SystemExit("the tracee did not stop for tracing")
    ptrace(
        PTRACE_SETOPTIONS,
        child,
        0,
        PTRACE_O_TRACESYSGOOD
        | PTRACE_O_TRACEFORK
        | PTRACE_O_TRACEVFORK
        | PTRACE_O_TRACECLONE
        | PTRACE_O_TRACEEXEC
        | PTRACE_O_EXITKILL,
    )
    ptrace(PTRACE_SYSCALL, child, 0, 0)

    entering: dict[int, bool] = {child: True}
    fresh: set[int] = set()
    pending: dict[int, dict] = {}
    observations: list[dict] = []
    processes: list[dict] = [{"pid": child, "parent": None, "event": "start"}]
    exit_code = None

    while entering:
        try:
            pid, status = os.waitpid(-1, WALL)
        except ChildProcessError:
            break
        if os.WIFEXITED(status) or os.WIFSIGNALED(status):
            if pid == child:
                exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -os.WTERMSIG(status)
            entering.pop(pid, None)
            pending.pop(pid, None)
            continue
        if not os.WIFSTOPPED(status):
            continue
        event = status >> 16
        sig = os.WSTOPSIG(status)

        if event in (EVENT_FORK, EVENT_VFORK, EVENT_CLONE):
            message = ctypes.c_ulonglong(0)
            ptrace(PTRACE_GETEVENTMSG, pid, 0, ctypes.byref(message))
            number = int(message.value)
            entering.setdefault(number, True)
            fresh.add(number)
            processes.append(
                {
                    "pid": number,
                    "parent": pid,
                    "event": {EVENT_FORK: "fork", EVENT_VFORK: "vfork", EVENT_CLONE: "clone"}[event],
                }
            )
            ptrace(PTRACE_SYSCALL, pid, 0, 0)
            continue
        if event == EVENT_EXEC:
            # The exec replaces the image; the next stop is an entry stop.
            entering[pid] = True
            ptrace(PTRACE_SYSCALL, pid, 0, 0)
            continue

        if sig == (signal.SIGTRAP | 0x80):
            try:
                regs = registers(pid)
            except OSError:
                entering.pop(pid, None)
                continue
            info = syscall_info(pid)
            if info is not None and info.op == SYSCALL_INFO_ENTRY:
                number, args = info.entry()
                if number == SYS_GETRANDOM:
                    pending[pid] = {
                        "ip": info.ip,
                        "buffer": args[0],
                        "length": args[1],
                        "flags": args[2],
                    }
                else:
                    pending.pop(pid, None)
            elif info is not None and info.op == SYSCALL_INFO_EXIT:
                record = pending.pop(pid, None)
                if record is not None:
                    try:
                        observations.append(
                            classify(
                                pid,
                                record["ip"],
                                record["buffer"],
                                record["length"],
                                record["flags"],
                                info.return_value(),
                            )
                        )
                    except OSError:
                        pass
            elif info is None:
                # Kernels without GET_SYSCALL_INFO: fall back to the register convention.
                if entering.get(pid, True):
                    entering[pid] = False
                    if regs.orig_rax == SYS_GETRANDOM:
                        pending[pid] = {
                            "ip": regs.rip,
                            "buffer": regs.rdi,
                            "length": regs.rsi,
                            "flags": regs.rdx,
                        }
                else:
                    entering[pid] = True
                    record = pending.pop(pid, None)
                    if record is not None:
                        try:
                            observations.append(
                                classify(
                                    pid,
                                    record["ip"],
                                    record["buffer"],
                                    record["length"],
                                    record["flags"],
                                    regs.rax,
                                )
                            )
                        except OSError:
                            pass
            ptrace(PTRACE_SYSCALL, pid, 0, 0)
            continue

        # A real signal or the initial SIGSTOP of a new task.
        if pid in fresh:
            fresh.discard(pid)
            entering[pid] = True
            ptrace(PTRACE_SYSCALL, pid, 0, 0)
            continue
        ptrace(PTRACE_SYSCALL, pid, 0, sig)

    return {
        "command": command,
        "kernel": platform.release(),
        "platform": platform.platform(),
        "exit_code": exit_code,
        "processes": processes,
        "observations": observations,
        "summary": {
            "observations": len(observations),
            "runtime_internal_probes": sum(
                1 for o in observations if o["classification"] == "runtime-internal-probe"
            ),
            "other": sum(1 for o in observations if o["classification"] != "runtime-internal-probe"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("no command given")

    report = run(command)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if args.summary:
        print(f"command  {' '.join(report['command'])}")
        print(f"processes {len(report['processes'])}  observations {len(report['observations'])}")
        for observation in report["observations"]:
            checks = "".join(
                "1" if value else "0" for value in observation["admission_checks"].values()
            )
            print(
                f"  pid {observation['pid']:>6} {observation['module']}"
                f"+{observation['module_offset']} ({observation['caller_nearest_symbol']})"
                f" len {observation['length']} flags {observation['flags']}"
                f" ret {observation['return_value']}"
                f" buffer {observation['buffer_module']}+{observation['buffer_offset']}"
                f" [{checks}] {observation['classification']}"
            )
        print(json.dumps(report["summary"]))
    elif not args.json:
        print(json.dumps(report, indent=2))
    return 0 if report["exit_code"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
