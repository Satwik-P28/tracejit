//! fs-verity digest measurement (experimental, Linux only).
//!
//! `FS_IOC_MEASURE_VERITY` returns the Merkle-tree root of a file that is protected by
//! fs-verity. The root covers the file's content, and a verity file cannot be modified in
//! place, so comparing two roots is equivalent to comparing content — without reading the
//! bytes. It says nothing about the path, ownership, permissions or mount identity, which
//! remain the job of the metadata guards.
//!
//! Every failure that means "this file or filesystem does not offer verity" is reported as
//! `Ok(None)` so callers fall back to strict hashing. Only an operational error on a
//! verity-capable file is surfaced.

use std::fs::File;
use std::io;
use std::os::fd::{AsRawFd, RawFd};
use std::path::Path;

/// `FS_VERITY_HASH_ALG_SHA256`, the only algorithm this module trusts.
const FS_VERITY_HASH_ALG_SHA256: u16 = 1;
/// `_IOR('f', 9, struct fsverity_digest)` with a 4-byte header.
const FS_IOC_MEASURE_VERITY: libc::c_ulong = 0xc004_6686;
const DIGEST_LEN: usize = 32;

#[repr(C)]
struct DigestHeader {
    algorithm: u16,
    size: u16,
}

fn unsupported(error: &io::Error) -> bool {
    matches!(
        error.raw_os_error(),
        Some(libc::ENOTTY)
            | Some(libc::EOPNOTSUPP)
            | Some(libc::EINVAL)
            | Some(libc::EPERM)
            | Some(libc::ENODATA)
    )
}

fn measure_fd(fd: RawFd) -> io::Result<Option<[u8; DIGEST_LEN]>> {
    // Header immediately followed by the digest, as the kernel ABI specifies.
    let mut buffer = [0_u8; std::mem::size_of::<DigestHeader>() + DIGEST_LEN];
    {
        let header = unsafe { &mut *buffer.as_mut_ptr().cast::<DigestHeader>() };
        header.algorithm = FS_VERITY_HASH_ALG_SHA256;
        header.size = DIGEST_LEN as u16;
    }
    let result = unsafe { libc::ioctl(fd, FS_IOC_MEASURE_VERITY, buffer.as_mut_ptr()) };
    if result != 0 {
        let error = io::Error::last_os_error();
        return if unsupported(&error) {
            Ok(None)
        } else {
            Err(error)
        };
    }
    let header = unsafe { &*buffer.as_ptr().cast::<DigestHeader>() };
    if header.algorithm != FS_VERITY_HASH_ALG_SHA256 || header.size as usize != DIGEST_LEN {
        return Ok(None);
    }
    let mut digest = [0_u8; DIGEST_LEN];
    digest.copy_from_slice(&buffer[std::mem::size_of::<DigestHeader>()..]);
    Ok(Some(digest))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::os::unix::fs::PermissionsExt;

    fn temp_file(content: &[u8]) -> (tempfile::TempDir, std::path::PathBuf) {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("input");
        let mut file = File::create(&path).unwrap();
        file.write_all(content).unwrap();
        (directory, path)
    }

    #[test]
    fn an_ordinary_file_reports_no_verity_digest() {
        // Either the filesystem supports verity and the file is not enrolled (ENODATA),
        // or it does not support it at all. Both must be a clean "no digest", never an
        // error, so validation falls back to hashing.
        let (_directory, path) = temp_file(b"ordinary");
        assert_eq!(measure_path(&path).unwrap(), None);
    }

    #[test]
    fn measuring_an_absent_file_is_an_error_not_a_digest() {
        let directory = tempfile::tempdir().unwrap();
        assert!(measure_path(&directory.path().join("absent")).is_err());
    }

    #[test]
    fn an_unreadable_file_is_not_mistaken_for_enrolled_content() {
        let (_directory, path) = temp_file(b"secret");
        let mut permissions = std::fs::metadata(&path).unwrap().permissions();
        permissions.set_mode(0o000);
        std::fs::set_permissions(&path, permissions).unwrap();
        // Running as root would defeat the premise; only assert when the open really fails.
        if File::open(&path).is_err() {
            assert!(measure_path(&path).is_err());
        }
    }
}

/// Measures the fs-verity root of `path`.
///
/// `Ok(None)` means the file is not verity-protected or the filesystem does not implement
/// verity; callers must then hash the content. `Err` means the file exists but could not
/// be opened, which is reported as a guard failure by the caller.
pub fn measure_path(path: &Path) -> io::Result<Option<[u8; DIGEST_LEN]>> {
    #[cfg(test)]
    if let Some(overridden) = test_digest() {
        // Unit tests exercise the digest-match and digest-mismatch branches on filesystems
        // that do not implement fs-verity. Thread-local so parallel tests never see it.
        return Ok(overridden);
    }
    let file = File::open(path)?;
    measure_fd(file.as_raw_fd())
}

#[cfg(test)]
thread_local! {
    static TEST_DIGEST: std::cell::Cell<Option<Option<[u8; DIGEST_LEN]>>> =
        const { std::cell::Cell::new(None) };
}

#[cfg(test)]
pub(crate) fn set_test_digest(value: Option<Option<[u8; DIGEST_LEN]>>) {
    TEST_DIGEST.with(|slot| slot.set(value));
}

#[cfg(test)]
fn test_digest() -> Option<Option<[u8; DIGEST_LEN]>> {
    TEST_DIGEST.with(|slot| slot.get())
}
