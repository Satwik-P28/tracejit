# Phase 2G: what the glibc `getrandom` actually is

Verdict: on this host the single startup `getrandom(8, GRND_NONBLOCK)` is **glibc's allocator
pointer-guard key**, issued from `ptmalloc_init`/`tcache_key_initialize` inside the runtime. It is
not the loader, not the application, and not cryptographic use. It cannot be removed with a tunable.

## Exact artifacts

| Artifact | Version | Build ID |
| --- | --- | --- |
| `/lib/x86_64-linux-gnu/libc.so.6` | Ubuntu GLIBC 2.39-0ubuntu8.9 | `a4a7992a8e66555c8141ab2a08a8465ff6e0ea65` |
| `/lib64/ld-linux-x86-64.so.2` | same release | `0d77dbd4379bf0b5af3e05be7fb6af1e4cea7c96` |
| `/usr/bin/sed` | GNU sed, PIE, stripped | `6129d031484e5d6aa47d856763b37c6da90a863e` |
| `/usr/bin/tr` | GNU coreutils, PIE, stripped | `1a204c9f32887974c41595eba4d31afcec2ef74f` |

Kernel: `6.1.102`, x86_64, Ubuntu 24.04 userspace.

## Call site

`strace -f -k -e trace=getrandom sed 's/a/A/' /tmp/in.txt`:

```text
getrandom("\xde\x03\x94\x70\x16\xb2\xe3\xb7", 8, GRND_NONBLOCK) = 8
 > libc.so.6(timer_settime+0x1079) [0xa9e89]
 > libc.so.6(malloc+0x215) [0xad965]
 > libc.so.6(__strdup+0x1f) [0xb445f]
 > libselinux.so.1() [0x722c]
 > libselinux.so.1() [0x72e3]
 > ld-linux-x86-64.so.2(...) [...]
```

`objdump -d libc.so.6` at the reported offset shows the syscall itself:

```text
a9e82: mov    $0x13e,%eax        # __NR_getrandom = 318
a9e87: syscall
a9e89: lea    -0x30(%rbp),%rbx   # return address strace reported
a9e8d: cmp    $0x8,%rax
```

The caller at `malloc+0x215` (0xad965) is the return address of the call to the inlined
initialiser; the buffer is `&tcache_key` in libc's BSS (`base + 0x20b178` on this host). So the call
is allocator-internal: the value is used only as the tcache double-free guard, never handed to the
program.

## Classification of every observed source

| Category | Observed here? | Evidence |
| --- | --- | --- |
| Allocator-internal entropy | **yes, exactly one call** | site above, destination in libc BSS |
| Dynamic-loader entropy | no | `ld.so` frames are callers of libc's allocation path; no loader-issued `getrandom` appears |
| Application-requested randomness | not in these tools; fixture case `getrandom` does this deliberately | the fixture's 1-byte `getrandom` is classified `Nondeterministic` |
| Cryptographic randomness | none observed in the surveyed tools | a crypto call would target an application buffer; the site check refuses that |
| Language-runtime initialisation | no separate call; CPython also reads PID and clocks | its own reasons list those, not just randomness |
| Unrecognised randomness | none | one call per process, fully accounted for |

Position in the trace was not used as evidence; the arguments, return value, instruction offset,
module build ID, destination address, containing mapping and the ELF segment that owns the offset
were.

## Tunables and versions

- `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`: **does not remove it**. `tcache_key_initialize` is
  called from `ptmalloc_init` under `#if USE_TCACHE`, i.e. at malloc initialisation, not from
  lazily created tcache instances. Measured with `strace`; resulted in the same one call.
- `GLIBC_TUNABLES=glibc.malloc.tcache_key=...`: **no such tunable**. The glibc 2.41 manual's malloc
  tunable list contains `tcache_count`, `tcache_unsorted_limit`, `tcache_max`, `trim_threshold`,
  etc., but no tcache key; setting the unknown name was silently ignored and the call remained.
- Version history (source-level, not executed on this host): the tcache key and its `getrandom`
  first appear in the 2.34-era "Harden tcache double-free check" patch, which calls
  `tcache_key_initialize()` from `ptmalloc_init`; the same initialiser is present through 2.35,
  2.39, 2.40 and 2.41. A 2024 patch only changes which `__getrandom_nocancel` variant is used
  (to preserve `errno`), not whether the call happens. Sources:
  <https://sourceware.org/pipermail/libc-alpha/2021-July/128671.html>,
  <https://sourceware.org/pipermail/libc-alpha/2022-August/141160.html>,
  <https://sourceware.org/pipermail/libc-alpha/2024-January/153848.html>,
  <https://github.com/bminor/glibc/blob/glibc-2.41/manual/tunables.texi>.
- **Static glibc does not avoid it.** `cc -static` of the fixture still emits
  `getrandom(8, GRND_NONBLOCK)`, because the same `ptmalloc_init` is linked in.
- **musl was not tested.** No musl toolchain or dynamic loader is installed on this host, so the
  claim that musl's allocator avoids this probe is recorded as **BLOCKED**, not as a result.

## Reproduction

```bash
strace -f -k -e trace=getrandom sed 's/a/A/' /tmp/in.txt
GLIBC_TUNABLES=glibc.malloc.tcache_count=0 strace -f -e trace=getrandom sed 's/a/A/' /tmp/in.txt
objdump -d --start-address=0xa9e70 --stop-address=0xa9ea0 /lib/x86_64-linux-gnu/libc.so.6
readelf -n /lib/x86_64-linux-gnu/libc.so.6 | grep -i 'build id'
cc -static -O2 -o /tmp/tj-static tests/fixtures/fixture_driver.c
strace -f -e trace=getrandom /tmp/tj-static plain_file_read /tmp
```
