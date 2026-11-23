# Kernel capability matrix for verified content identity

Phase Y asks one question: can a warm hit stop reading 105 MB of compiler binaries on the strength
of something cheaper than a full content hash, without weakening the contract? That requires a
mechanism whose guarantee is *identity of content*, not merely "the file is unlikely to change".

Four properties that are routinely conflated, and that this phase keeps apart:

| Property | Question it answers | Sufficient to replace a content hash? |
| --- | --- | --- |
| **Identity** | are these the same bytes? | yes — this is the property the guard needs |
| **Integrity** | have these bytes been corrupted or modified since some reference point? | only if the reference is the traced content *and* the check is per-read |
| **Authentication** | were these bytes produced by an entity I trust? | no — answers a different question, needs a trust root |
| **Immutability** | can these bytes change *now*? | no — a promise about the future, not a statement about the past |

A mechanism can give immutability without identity (`FS_IMMUTABLE_FL`), identity without
authentication (`FS_IOC_MEASURE_VERITY` compared against a pin this process recorded itself), and
authentication without immutability (a detached signature over a file that is still writable).

## The matrix

Primary sources: `Documentation/filesystems/fsverity.rst`,
`Documentation/admin-guide/device-mapper/verity.rst`, `include/uapi/linux/fsverity.h`,
`include/uapi/linux/fs.h` (`FS_IMMUTABLE_FL`, `FS_VERITY_FL`), `include/uapi/linux/stat.h`
(`STATX_ATTR_VERITY`), `fcntl(2)` seals, `chattr(1)`.

| # | Mechanism | Exact kernel guarantee | Property class | Privileges to establish | Filesystems | Survives rename | Inode replaceable | Content mutable in place | Metadata mutable | Hardlinks / symlinks | Usable unprivileged on a dev machine | Changes the user's files | Needs a separate contract |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **fs-verity** + `FS_IOC_MEASURE_VERITY` | The file's data pages are verified against a Merkle tree the kernel persists; `MEASURE` returns the digest *of the descriptor* (version, algorithm, log₂ block size, salt size, **data_size**, root hash, salt), in constant time. Reads that do not match fail with `EIO`/`SIGBUS`. | identity + integrity, per read | Enable: write access to the file, an `O_RDONLY` fd, and no writer open. The **filesystem** needs the `verity` feature, which is set at `mkfs` or with `tune2fs` — root. Observe: any reader. | ext4 ≥ 5.4 (`-O verity`), f2fs ≥ 5.4 (`-O verity`), btrfs ≥ 5.15 | yes (digest is per-inode, not per-name) | yes — the path can be repointed at a different inode, and the new inode simply has no digest | **no** — open-for-write and `truncate` fail with `EPERM` | yes (owner, mode, timestamps, xattrs are not measured) | hardlink: same inode, same digest. symlink: a symlink has no verity, so resolution can be redirected at the *name* level | enable: only on a verity-formatted fs with `CONFIG_FS_VERITY`; observe: yes | yes — enabling makes the file permanently read-only; it cannot be undone in place (dataclass) | no, if the pin is recorded at trace time by TraceJIT itself |
| 2 | **`FS_IMMUTABLE_FL`** | `write`, `truncate`, `rename`, `unlink`, `link`, and owner/mode changes are refused while the flag is set, for every caller | immutability only | `CAP_LINUX_IMMUTABLE` to set **and to clear** | ext4, xfs, btrfs, f2fs | the file cannot be renamed at all | not while set (unlink/link refused) | no | no | hardlink/link refused; a symlink can still be planted in another directory | no — the flag is not settable by an unprivileged owner | yes | yes — an immutability promise is not identity; a root writer can clear the flag and rewrite |
| 3 | **dm-verity** | A read-only device-mapper target verifies every data block against a hash tree whose root is supplied in the mapping table at load time; a mismatch fails the I/O | identity + integrity of a **block device** | `CAP_SYS_ADMIN` + `dmsetup` (root) | any block device | n/a | n/a | no — the mapping is read-only | n/a | n/a | no | yes, and it requires a dedicated device/partition and a key-management policy | yes — a whole-device contract, not a per-file one |
| 4 | **Read-only mount / bind mount, mount namespace** | Writes through the mount are refused by the VFS | immutability of a *subtree* | `CAP_SYS_ADMIN` to mount or remount | any | yes | yes — a writable mount of the same device elsewhere bypasses it | yes, through another mount | yes | unaffected | no | yes (fstab change) | yes — a mount is a policy, not a content identity |
| 5 | **`memfd` seals** (`F_ADD_SEALS`) | `F_SEAL_WRITE` (and `F_SEAL_FUTURE_WRITE`) make the shmem object unwritable; seals are irreversible | immutability + identity of a *shmem object* | none for one's own memfd | `memfd_create` only | n/a — no pathname | n/a | no | n/a | n/a | yes, but it cannot hold `/usr/bin/cc1` | no | yes |
| 6 | **Content-addressed installs** (Nix store, ostree, verity container layers) | The path contains the digest of the contents and the store is mounted/owned read-only; ostree deployments additionally use fs-verity | identity by construction + immutability | installation-time, root | varies | yes | not without changing the path | no | yes | unaffected | only if the user adopted the store | yes (the installation method) | yes — the guarantee is the installer's, not the kernel's |
| 7 | **IMA appraisal / measurement** | A policy hashes (or reads a stored signature for) files at `open`, records the result in a measurement log, and can refuse to open a file whose signature/hash does not match the policy | authentication + measurement | root: policy, keyring, xattrs | any with IMA enabled | n/a — applies at open | yes, and the new inode must satisfy the policy | yes, until the next open | EVM covers metadata xattrs | n/a | no | yes (policy + keys are machine-wide) | yes |
| 8 | **`statx` `STATX_ATTR_VERITY`** | Reports that the inode has fs-verity enabled (≥ 5.5); cheaper than `GETFLAGS` because it needs no open | *a flag*, not a guarantee | none | as fs-verity | yes | **yes — the replacement inode simply lacks the flag, which is detectable** | with fs-verity, no | yes | n/a | yes | no | no — it is a precondition check, not a proof |
| 9 | **`FS_IOC_GETFLAGS` `FS_VERITY_FL`** | Same information as #8, on an open descriptor | *a flag* | none | as fs-verity | yes | yes | no | yes | n/a | yes | no | no |
| 10 | **fscrypt** (for contrast) | Transparent per-file encryption; the *plaintext* is what fs-verity measures | confidentiality, not identity | keys, root | ext4, f2fs | yes | yes | yes | yes | n/a | no | yes | n/a — orthogonal |

## What each mechanism does and does not answer for TraceJIT

The threat the guard has to close is: *the bytes the command read at trace time are the bytes at
this path now*. Ranked by how directly they answer it:

1. **fs-verity measurement against a locally recorded pin** answers it exactly. It also *narrows*
   the documented restore-window limitation for that dependency: once verity is enabled the inode's
   content cannot be modified in place at all, so an in-place mutation between validation and
   restore is impossible rather than merely unobserved. Pathname replacement inside that window is
   still possible, and remains the documented V1 limitation. This is the only mechanism in the table
   that is (a) per file, (b) unprivileged to observe, (c) constant time, and (d) an identity
   statement rather than a policy statement.
2. **`STATX_ATTR_VERITY` / `FS_VERITY_FL`** are the *admission* test: they tell you a measurement
   will exist. On their own they prove nothing about content, because the answer is a single bit
   about an inode the caller has not yet identified with the recorded one.
3. **`FS_IMMUTABLE_FL`, read-only mounts, dm-verity, seals, content-addressed stores** all restrict
   who can change bytes. They do not say the bytes are the traced bytes, and every one of them
   requires either root, a dedicated device, a memfd, or an installation method — so each would need
   a separately named, weaker contract ("reproducible under an operator promise").
4. **IMA** answers a different question (is this file authorised by a machine-wide policy) and needs
   root, a policy and a keyring, so it cannot be a per-user accelerator.
5. **fscrypt** is listed only to exclude it: it protects confidentiality and does not constrain
   content identity at all.

## Consequences for the design

* Only fs-verity can replace the hash comparison inside the **existing** `tracejit.strict-hash.v1`
  contract, because it is the only mechanism that is a per-file, per-read content identity that an
  unprivileged process can observe.
* Everything else in the table is either a weaker contract (needs a new name, opt-in, and must never
  be reported as Strict) or is unavailable to the workloads that matter (`/usr/lib/gcc/.../cc1` on a
  stock ext4 root filesystem).
* The **pin must be recorded by TraceJIT**, not supplied by the user: with a self-recorded pin,
  fs-verity supplies identity, and no trust root, signature or keyring is needed. That is why #1
  needs no separate contract, and why it is the only mechanism this phase prototyped.

## Host capability, measured (2026-11-23)

Full JSON: `benchmarks/results/phase_y/verity-probe.json`, produced by
`scripts/phase_y_verity_probe.py`.

| Fact | Value | How it was established |
| --- | --- | --- |
| Kernel | `6.1.102` (Ubuntu 24.04.5, x86_64) | `uname -a` |
| `CONFIG_FS_VERITY` | **not set** | `/boot/config-6.1.102`: `# CONFIG_FS_VERITY is not set` |
| Root filesystem | ext4, `rw,relatime` on `/dev/vda` | `/proc/self/mountinfo` |
| `FS_IOC_MEASURE_VERITY` on a disposable file | `EOPNOTSUPP` (95) | ioctl with the exact `_IOWR('f',134,4)` request |
| `FS_IOC_ENABLE_VERITY` | `EOPNOTSUPP` (95) | ioctl with the exact 128-byte `fsverity_enable_arg` |
| Mis-numbered `MEASURE_VERITY` (wrong `_IOC_SIZE`) | `ENOTTY` (25) | same file, request `0x40286685` |
| Cost of one failing measurement | ≈ 1.7 µs (Python `fcntl.ioctl` wrapper included) | 500 iterations |
| Effective capabilities | none (`CapEff: 0`), `NoNewPrivs: 1` | `/proc/self/status` |
| User namespaces | permitted (`unprivileged_userns_clone=1`) | `unshare -Ur true` |
| `/dev/kvm` | present, `crw-rw---- root:kvm`, **not** accessible to this user | `os.access(..., R_OK|W_OK)` false |
| qemu / firecracker | absent; `apt-get download` has no package lists and installing needs root | `shutil.which`, `apt-get download` |

**Erratum worth recording.** The kernel documentation says a kernel built without
`CONFIG_FS_VERITY` fails the ioctls with `EOPNOTSUPP`, and that a filesystem that does not implement
fs-verity fails with `ENOTTY`. On this host a *correctly numbered* `MEASURE_VERITY` reaches ext4's
`fsverity_ioctl_measure()` stub and returns `EOPNOTSUPP`, while a request with the wrong `_IOC_SIZE`
misses the compiled-in case and returns `ENOTTY`. The same kernel therefore produces both errnos
depending on how the caller computed the request number. Any classifier that treats only one of them
as "unsupported" would misread a missing kernel feature as an I/O error, so `is_unavailable_errno`
accepts `ENODATA`, `ENOTTY`, `EOPNOTSUPP`, `ENOPKG` and `EINVAL` alike.

**Why no verity-capable environment was reachable.** Establishing fs-verity needs a filesystem with
the `verity` feature and a kernel with `CONFIG_FS_VERITY`; neither can be changed without
`CAP_SYS_ADMIN`, which this sandbox does not have (`CapEff: 0`, `NoNewPrivs: 1`, no `sudo`). A
disposable VM would need KVM (present but group-restricted) or a userspace emulator (absent, and
installing one needs root). A `mount(2)` of a loop-backed ext4 image inside an unprivileged user
namespace is not available either: ext4 is not `FS_USERNS_MOUNT`. The prototype is therefore
exercised against the real kernel for **every refusal path** and against an injected measurement for
the admission paths, and no verity speedup is claimed anywhere in
`docs/PHASE_Y_REPORT.md`.
