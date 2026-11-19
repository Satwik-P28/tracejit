//! Phase X regressions for content validation.
//!
//! Phase X measured that one compiler warm hit read the same compiler binaries three times, so it
//! tried caching the digest for later guards of the same path. An adversarial test showed why that
//! is unsound: a same-size rewrite that lands inside one filesystem timestamp tick leaves
//! `mtime`, `ctime` and `size` identical, so a cached digest would be handed to the later guard
//! and the changed content would be missed. The cache was rejected. These regressions keep the
//! strict behaviour honest: every content guard reads the bytes and a rewrite that tries to hide
//! behind preserved metadata still deoptimizes.

use super::*;

#[cfg(unix)]
fn rewrite_preserving_mtime(path: &Path, bytes: &[u8]) {
    use std::os::unix::ffi::OsStrExt;
    let before = fingerprint(path).unwrap();
    fs::write(path, bytes).unwrap();
    let times = [
        libc::timespec {
            tv_sec: before.accessed_ns.div_euclid(1_000_000_000) as libc::time_t,
            tv_nsec: (before.accessed_ns.rem_euclid(1_000_000_000)) as _,
        },
        libc::timespec {
            tv_sec: before.modified_ns.div_euclid(1_000_000_000) as libc::time_t,
            tv_nsec: (before.modified_ns.rem_euclid(1_000_000_000)) as _,
        },
    ];
    let path_bytes = std::ffi::CString::new(path.as_os_str().as_bytes()).expect("path has no NUL");
    // SAFETY: `path_bytes` is a valid NUL-terminated path and `times` has two elements.
    let result = unsafe { libc::utimensat(libc::AT_FDCWD, path_bytes.as_ptr(), times.as_ptr(), 0) };
    assert_eq!(result, 0, "utimensat failed");
}

#[cfg(unix)]
#[test]
fn a_same_size_rewrite_in_the_same_timestamp_tick_is_still_detected() {
    // The counterexample that rejected the shared-digest experiment: the rewrite happens
    // immediately after the first observation, so `ctime` can fall in the same coarse timestamp
    // tick and the metadata looks untouched. A content guard must still read the bytes.
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("input");
    fs::write(&path, b"AAAA").unwrap();
    let guards = vec![Guard::FileHash {
        path: path.clone(),
        expected: hash_file(&path).unwrap(),
    }];
    assert!(validate_all(&guards, GuardMode::Strict).failure.is_none());

    rewrite_preserving_mtime(&path, b"BBBB");
    assert_eq!(fs::read(&path).unwrap(), b"BBBB");
    let before = fingerprint(&path).unwrap();
    assert_eq!(before.size, 4, "the rewrite is deliberately the same size");

    let report = validate_all(&guards, GuardMode::Strict);
    assert!(
        report.failure.is_some(),
        "a same-size rewrite with preserved timestamps must deoptimize"
    );
}

#[cfg(unix)]
#[test]
fn a_content_guard_is_rechecked_even_when_the_path_appears_twice_in_one_pass() {
    // Two content guards for the same path are two independent observations. The second must not
    // silently inherit the first one's evidence: with the same expected digest it passes only
    // because the bytes really still match.
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("input");
    fs::write(&path, b"content").unwrap();
    let digest = hash_file(&path).unwrap();
    let guards = vec![
        Guard::FileHash {
            path: path.clone(),
            expected: digest,
        },
        Guard::FileHash {
            path: path.clone(),
            expected: digest,
        },
    ];
    assert_eq!(validate_all(&guards, GuardMode::Strict).passed, 2);

    rewrite_preserving_mtime(&path, b"CONTENT");
    let report = validate_all(&guards, GuardMode::Strict);
    assert_eq!(report.passed, 0);
    assert_eq!(
        report.failure.expect("content changed").reason,
        "file content changed"
    );
}

#[cfg(unix)]
#[test]
fn a_content_guard_fails_at_its_own_position_in_record_order() {
    let root = tempfile::tempdir().unwrap();
    let good = root.path().join("good");
    let bad = root.path().join("bad");
    fs::write(&good, b"content").unwrap();
    fs::write(&bad, b"content").unwrap();
    let correct = hash_file(&good).unwrap();
    let wrong = Hash::from(blake3::hash(b"not the content"));
    let guards = vec![
        Guard::FileHash {
            path: good,
            expected: correct,
        },
        Guard::FileHash {
            path: bad,
            expected: wrong,
        },
    ];
    let report = validate_all(&guards, GuardMode::Strict);
    assert_eq!(report.checked, 2);
    assert_eq!(report.passed, 1);
    let failure = report.failure.expect("the second guard must fail");
    assert_eq!(failure.reason, "file content changed");
    assert_eq!(failure.expected, wrong.to_string());
}
