//! Kernel-verified content identity (fs-verity), Phase Y prototype.
//!
//! The Phase X profile attributes 91.8 % of warm-hit validation time to content hashing:
//! 107,160,458 bytes read through 1,737 `read` calls for 43.4 MB of distinct content. Replacing
//! that with something cheaper is only admissible if the replacement is an *equally strong* proof
//! that the live bytes equal the traced bytes.
//!
//! fs-verity is the one Linux mechanism that offers exactly that trade. The kernel documentation
//! states it directly: "fs-verity is essentially a way to hash a file in constant time, subject to
//! the caveat that reads which would violate the hash will fail at runtime"
//! (`Documentation/filesystems/fsverity.rst`). `FS_IOC_MEASURE_VERITY` returns the *fs-verity file
//! digest*, a hash of the `fsverity_descriptor` — the Merkle root plus the data size, hash
//! algorithm, block size and salt — and every subsequent read of the file is verified against that
//! Merkle tree, so a content change either fails the read (`EIO`/`SIGBUS`) or cannot happen at all
//! (the file is read-only; open-for-write and `truncate` fail with `EPERM`).
//!
//! This module never *computes* an fs-verity digest. It only pins a digest the kernel reported and
//! later compares the kernel's answer with that pin. That removes an entire class of bugs: there is
//! no second implementation of the Merkle layout, no assumption about salt, block size or algorithm
//! numbering, and an unknown future algorithm is handled by comparing its opaque bytes rather than
//! by failing to parse them.
//!
//! ## The three outcomes of a measurement
//!
//! [`decide`] is the whole admission rule, written as a pure function so the adversarial matrix can
//! be exercised without a verity-capable kernel:
//!
//! | Measurement | Verdict | Why |
//! | --- | --- | --- |
//! | digest bytes equal the pin, same algorithm | `Proven` | kernel asserts the pinned content identity |
//! | same algorithm, different bytes | `Contradicted` | with overwhelming probability the content is not the traced content; refusing is free |
//! | different algorithm or length | `FallBackToHash` | the two digests are not comparable, so nothing is proven either way |
//! | unavailable (`ENODATA`, `ENOTTY`, `EOPNOTSUPP`, `ENOPKG`, `EINVAL`) | `FallBackToHash` | no kernel answer exists here |
//! | any other ioctl failure | `FallBackToHash` | an unexpected failure must not be read as agreement |
//!
//! The fallback is the *existing* Strict behaviour: read the file and compare its BLAKE3 digest with
//! the recorded one. A verity guard is an accelerator for a predicate that is still fully checked
//! wherever the kernel cannot speak, so an unsupported host, a downgraded file, a replaced inode or
//! a kernel built without `CONFIG_FS_VERITY` all keep exactly today's semantics and today's cost.

use serde::{Deserialize, Serialize};
use std::fs::File;
use std::os::fd::AsRawFd;
use std::path::Path;

/// The digest length budget. SHA-512 is the longest algorithm fs-verity defines today (64 bytes);
/// a longer digest from a future algorithm is reported as malformed rather than truncated.
pub const MAX_DIGEST_LEN: usize = 64;

/// `_IOWR('f', 134, struct fsverity_digest)`, whose `_IOC_SIZE` is the 4-byte fixed header.
///
/// The number must be exact. A mis-sized request still reaches the filesystem, but it misses the
/// compiled-in `case` and falls through to `-ENOTTY`; the correctly-sized one reaches
/// `fsverity_ioctl_measure()`, whose `CONFIG_FS_VERITY=n` stub returns `-EOPNOTSUPP`. Both mean
/// "no verity here", which is why [`is_unavailable_errno`] accepts both.
const FS_IOC_MEASURE_VERITY: libc::c_ulong = 0xc004_6686;

/// A content identity as the kernel reported it.
///
/// The pin is opaque: it is compared byte for byte with a later measurement, never interpreted.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct VerityPin {
    /// Hash algorithm the kernel reported for this file's Merkle tree.
    pub algorithm: u16,
    /// The digest exactly as `FS_IOC_MEASURE_VERITY` returned it.
    #[serde(with = "hex_digest")]
    pub digest: Vec<u8>,
}

impl VerityPin {
    pub fn new(algorithm: u16, digest: Vec<u8>) -> Self {
        Self { algorithm, digest }
    }

    /// Short rendering for diagnostics.
    pub fn short(&self) -> String {
        let hex = self
            .digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        format!(
            "alg{}:{}…",
            self.algorithm,
            hex.chars().take(16).collect::<String>()
        )
    }
}

/// What one `FS_IOC_MEASURE_VERITY` attempt produced.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MeasureOutcome {
    /// The kernel answered with a digest.
    Measured { algorithm: u16, digest: Vec<u8> },
    /// fs-verity cannot answer for this file on this system. The errno is retained for diagnostics.
    Unavailable { errno: i32 },
    /// The ioctl failed in a way the fs-verity documentation does not describe as "not applicable".
    Failed { errno: i32 },
    /// The kernel answered with a structurally impossible digest.
    Malformed { detail: &'static str },
}

/// Why a verity guard needs the full content hash after all.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FallbackReason {
    /// No verity answer exists here (`ENODATA`, `ENOTTY`, `EOPNOTSUPP`, `ENOPKG`, `EINVAL`, ...).
    Unavailable { errno: i32 },
    /// The ioctl failed for another reason.
    Failed { errno: i32 },
    /// The kernel used a different hash algorithm, so the digests are not comparable.
    AlgorithmMismatch { pinned: u16, measured: u16 },
    /// The kernel returned a different digest length, so the digests are not comparable.
    LengthMismatch { pinned: usize, measured: usize },
    /// The kernel returned an unusable digest.
    Malformed { detail: &'static str },
}

/// The admission decision for one verity guard.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VerityVerdict {
    /// The kernel's measurement equals the pin: the content identity holds.
    Proven,
    /// The kernel's measurement contradicts the pin: refuse without reading the file.
    Contradicted {
        pinned_algorithm: u16,
        pinned_len: usize,
        measured_algorithm: u16,
        measured_len: usize,
    },
    /// Nothing was proven either way; the caller must fall back to full content hashing.
    FallBackToHash(FallbackReason),
}

/// The entire admission rule. Pure, total, and independent of the kernel.
pub fn decide(pin: &VerityPin, outcome: &MeasureOutcome) -> VerityVerdict {
    match outcome {
        MeasureOutcome::Unavailable { errno } => {
            VerityVerdict::FallBackToHash(FallbackReason::Unavailable { errno: *errno })
        }
        MeasureOutcome::Failed { errno } => {
            VerityVerdict::FallBackToHash(FallbackReason::Failed { errno: *errno })
        }
        MeasureOutcome::Malformed { detail } => {
            VerityVerdict::FallBackToHash(FallbackReason::Malformed { detail })
        }
        MeasureOutcome::Measured { algorithm, digest } => {
            if *algorithm != pin.algorithm {
                return VerityVerdict::FallBackToHash(FallbackReason::AlgorithmMismatch {
                    pinned: pin.algorithm,
                    measured: *algorithm,
                });
            }
            if digest.len() != pin.digest.len() {
                return VerityVerdict::FallBackToHash(FallbackReason::LengthMismatch {
                    pinned: pin.digest.len(),
                    measured: digest.len(),
                });
            }
            if digest == &pin.digest {
                VerityVerdict::Proven
            } else {
                VerityVerdict::Contradicted {
                    pinned_algorithm: pin.algorithm,
                    pinned_len: pin.digest.len(),
                    measured_algorithm: *algorithm,
                    measured_len: digest.len(),
                }
            }
        }
    }
}

/// Mapping from errno to "fs-verity cannot answer here".
///
/// Measured erratum worth recording: the documentation says a kernel built without
/// `CONFIG_FS_VERITY` fails with `EOPNOTSUPP`, but an ext4 file on a 6.1 kernel without that option
/// fails with `ENOTTY`, because ext4 never registers the ioctl handler. Any classifier that keyed
/// on `EOPNOTSUPP` alone would misread a missing kernel feature as an unexpected error, so every
/// "not applicable" errno is treated the same way: fall back to hashing.
pub fn is_unavailable_errno(errno: i32) -> bool {
    matches!(
        errno,
        libc::ENODATA | libc::ENOTTY | libc::EOPNOTSUPP | libc::ENOPKG | libc::EINVAL
    )
}

#[repr(C)]
struct FsVerityDigest {
    digest_algorithm: u16,
    digest_size: u16,
    digest: [u8; MAX_DIGEST_LEN],
}

/// Measure the fs-verity file digest of an already-opened descriptor.
///
/// The descriptor is used as given: the caller has already established what `path` names, and
/// measuring the same open file description it will read (or has read) keeps the metadata and
/// content halves of a guard pair on one inode.
pub fn measure(file: &File) -> MeasureOutcome {
    let mut request = FsVerityDigest {
        digest_algorithm: 0,
        digest_size: MAX_DIGEST_LEN as u16,
        digest: [0; MAX_DIGEST_LEN],
    };
    // SAFETY: the pointer is to a live, correctly sized `FsVerityDigest` for the duration of the
    // call, and `FS_IOC_MEASURE_VERITY` writes at most `digest_size` bytes past the 4-byte header,
    // which fits the 64-byte array.
    let result = unsafe {
        libc::ioctl(
            file.as_raw_fd(),
            FS_IOC_MEASURE_VERITY,
            &mut request as *mut FsVerityDigest,
        )
    };
    if result != 0 {
        let errno = std::io::Error::last_os_error()
            .raw_os_error()
            .unwrap_or(libc::EIO);
        return if is_unavailable_errno(errno) {
            MeasureOutcome::Unavailable { errno }
        } else {
            MeasureOutcome::Failed { errno }
        };
    }
    let length = usize::from(request.digest_size);
    if length == 0 || length > MAX_DIGEST_LEN {
        return MeasureOutcome::Malformed {
            detail: "digest length outside 1..=64",
        };
    }
    MeasureOutcome::Measured {
        algorithm: request.digest_algorithm,
        digest: request.digest[..length].to_vec(),
    }
}

/// Produce a pin for a file, but only under the ordering the correctness argument requires.
///
/// The measurement is taken **before** the caller reads the bytes, and the pin is only returned
/// when the kernel answered. That ordering is what binds the pin to the bytes: once verity is
/// enabled the kernel verifies every read against the Merkle tree the digest describes, and the
/// content can no longer be modified in place, so a digest measured before the read describes
/// exactly the bytes the read returns. A digest measured *after* the read would instead leave a
/// window in which the content could be replaced and verity re-enabled over the replacement.
pub fn pin_before_read(file: &File) -> Option<VerityPin> {
    match measure(file) {
        MeasureOutcome::Measured { algorithm, digest } => Some(VerityPin::new(algorithm, digest)),
        _ => None,
    }
}

/// What a filesystem answers when asked whether it can do fs-verity at all.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub enum SupportProbe {
    /// The kernel produced a verity digest for the probed file: fs-verity works here.
    Supported { algorithm: u16, digest_len: usize },
    /// fs-verity is configured but the probed file has none enabled; the filesystem answered.
    NotEnabled { errno: i32 },
    /// No fs-verity support: kernel option, filesystem feature or ioctl missing.
    Unsupported { errno: i32 },
    /// The probed path does not exist or cannot be opened.
    Unreadable { detail: String },
}

impl SupportProbe {
    /// Whether a verity-backed guard could ever be recorded on this filesystem.
    pub fn is_usable(&self) -> bool {
        matches!(self, Self::Supported { .. } | Self::NotEnabled { .. })
    }

    pub fn describe(&self) -> String {
        match self {
            Self::Supported {
                algorithm,
                digest_len,
            } => format!("available (algorithm {algorithm}, {digest_len}-byte digest)"),
            Self::NotEnabled { errno } => format!(
                "available on this filesystem; the probed file has no verity digest (errno {errno})"
            ),
            Self::Unsupported { errno } => format!("unavailable (errno {errno})"),
            Self::Unreadable { detail } => format!("unknown ({detail})"),
        }
    }
}

/// Probe fs-verity support on the filesystem holding `path`, read-only.
///
/// A regular file is opened once and measured. `ENODATA` means the filesystem answered and the file
/// simply has no verity metadata, which is the expected answer for every file on a verity-capable
/// system that was not itself enabled; every other "not applicable" errno means the mechanism is
/// missing. Nothing is enabled, created or modified by this probe.
pub fn probe_support(path: &Path) -> SupportProbe {
    match File::open(path) {
        Ok(file) => match measure(&file) {
            MeasureOutcome::Measured { algorithm, digest } => SupportProbe::Supported {
                algorithm,
                digest_len: digest.len(),
            },
            MeasureOutcome::Unavailable { errno } if errno == libc::ENODATA => {
                SupportProbe::NotEnabled { errno }
            }
            MeasureOutcome::Unavailable { errno } => SupportProbe::Unsupported { errno },
            MeasureOutcome::Failed { errno } => SupportProbe::Unsupported { errno },
            MeasureOutcome::Malformed { detail: _ } => {
                SupportProbe::Unsupported { errno: libc::EIO }
            }
        },
        Err(error) => SupportProbe::Unreadable {
            detail: error.to_string(),
        },
    }
}

mod hex_digest {
    use serde::de::Error as _;
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(bytes: &[u8], serializer: S) -> Result<S::Ok, S::Error> {
        let mut hex = String::with_capacity(bytes.len() * 2);
        for byte in bytes {
            hex.push_str(&format!("{byte:02x}"));
        }
        serializer.serialize_str(&hex)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Vec<u8>, D::Error> {
        let text = String::deserialize(deserializer)?;
        if text.len() % 2 != 0 {
            return Err(D::Error::custom("odd-length hex digest"));
        }
        let mut bytes = Vec::with_capacity(text.len() / 2);
        for index in (0..text.len()).step_by(2) {
            let byte = u8::from_str_radix(&text[index..index + 2], 16)
                .map_err(|error| D::Error::custom(format!("bad hex digest: {error}")))?;
            bytes.push(byte);
        }
        Ok(bytes)
    }
}
