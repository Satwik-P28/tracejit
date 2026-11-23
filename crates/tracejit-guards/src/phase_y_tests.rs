//! Phase Y regressions: kernel-verified content identity.
//!
//! Two properties are pinned here.
//!
//! 1. The admission rule is total and one-directional: a kernel measurement can *only* prove
//!    content identity when it equals the pin. Every other outcome — unavailable, failed,
//!    malformed, a different algorithm, a different length, a different digest — either falls back
//!    to the full content hash or refuses. None of them accepts.
//! 2. On a host where fs-verity is absent, which is every host this phase could run on, a verity
//!    guard behaves exactly like `Guard::FileHash`: it reads the file, hashes it, and compares. The
//!    tests below exercise that on the real kernel, so the fallback is measured behaviour rather
//!    than a modelled one.

use super::verity::is_unavailable_errno;
use super::*;
use std::fs;
use std::io::Write;

fn pin(algorithm: u16, bytes: &[u8]) -> VerityPin {
    VerityPin::new(algorithm, bytes.to_vec())
}

fn measured(algorithm: u16, bytes: &[u8]) -> MeasureOutcome {
    MeasureOutcome::Measured {
        algorithm,
        digest: bytes.to_vec(),
    }
}

#[test]
fn a_matching_measurement_proves_content_identity() {
    let expected = pin(1, &[0xaa; 32]);
    assert_eq!(
        decide(&expected, &measured(1, &[0xaa; 32])),
        VerityVerdict::Proven
    );
}

#[test]
fn a_different_digest_contradicts_the_pin_without_reading_the_file() {
    // The only outcome that refuses without falling back: the kernel answered, with the same
    // algorithm and the same digest length, and the bytes differ.
    let expected = pin(1, &[0xaa; 32]);
    assert!(matches!(
        decide(&expected, &measured(1, &[0xbb; 32])),
        VerityVerdict::Contradicted { .. }
    ));
    // A single flipped bit is enough.
    let mut almost = [0xaa; 32];
    almost[31] ^= 1;
    assert!(matches!(
        decide(&expected, &measured(1, &almost)),
        VerityVerdict::Contradicted { .. }
    ));
}

#[test]
fn an_incomparable_measurement_never_accepts_and_never_refuses() {
    let expected = pin(1, &[0xaa; 32]);
    // Same algorithm, different length: the digests cannot be compared.
    assert_eq!(
        decide(&expected, &measured(1, &[0xaa; 16])),
        VerityVerdict::FallBackToHash(FallbackReason::LengthMismatch {
            pinned: 32,
            measured: 16,
        })
    );
    // Different algorithm, same bytes: still incomparable.
    assert_eq!(
        decide(&expected, &measured(2, &[0xaa; 32])),
        VerityVerdict::FallBackToHash(FallbackReason::AlgorithmMismatch {
            pinned: 1,
            measured: 2,
        })
    );
    // A longer digest than the pin can never be truncated into agreement.
    assert_eq!(
        decide(&expected, &measured(1, &[0xaa; 33])),
        VerityVerdict::FallBackToHash(FallbackReason::LengthMismatch {
            pinned: 32,
            measured: 33,
        })
    );
}

#[test]
fn every_unavailable_errno_falls_back() {
    let expected = pin(1, &[0xaa; 32]);
    for errno in [
        libc::ENODATA,
        libc::ENOTTY,
        libc::EOPNOTSUPP,
        libc::ENOPKG,
        libc::EINVAL,
    ] {
        assert!(
            is_unavailable_errno(errno),
            "errno {errno} must be unavailable"
        );
        assert_eq!(
            decide(&expected, &MeasureOutcome::Unavailable { errno }),
            VerityVerdict::FallBackToHash(FallbackReason::Unavailable { errno })
        );
    }
    // An errno the fs-verity documentation does not describe as "not applicable" is still never
    // read as agreement.
    for errno in [libc::EBADF, libc::EFAULT, libc::EIO, libc::EPERM] {
        assert_eq!(
            decide(&expected, &MeasureOutcome::Failed { errno }),
            VerityVerdict::FallBackToHash(FallbackReason::Failed { errno })
        );
    }
    assert_eq!(
        decide(
            &expected,
            &MeasureOutcome::Malformed {
                detail: "digest length outside 1..=64"
            }
        ),
        VerityVerdict::FallBackToHash(FallbackReason::Malformed {
            detail: "digest length outside 1..=64"
        })
    );
}

#[test]
fn a_future_algorithm_is_compared_as_opaque_bytes() {
    // TraceJIT never parses the digest, so an algorithm number it has never heard of is still
    // usable: equal bytes prove identity, different bytes contradict the pin.
    let expected = pin(0x1234, &[0x5a; 48]);
    assert_eq!(
        decide(&expected, &measured(0x1234, &[0x5a; 48])),
        VerityVerdict::Proven
    );
    assert!(matches!(
        decide(&expected, &measured(0x1234, &[0x5b; 48])),
        VerityVerdict::Contradicted { .. }
    ));
}

/// On this host fs-verity is unavailable (this is checked, not assumed), so a verity guard must
/// read and hash exactly like `Guard::FileHash`. This is the property that makes the guard safe to
/// ship on unsupported systems.
#[test]
fn a_verity_guard_without_kernel_support_hashes_the_file() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("input.bin");
    let mut file = fs::File::create(&path).expect("create");
    file.write_all(b"phase-y content").expect("write");
    drop(file);

    let expected = hash_file(&path).expect("hash");
    let probe = probe_support(&path);
    // Either the host cannot do fs-verity at all, or this file has no verity digest: in both cases
    // the guard has no proof available and must hash.
    assert!(
        !probe.is_usable() || matches!(probe, SupportProbe::NotEnabled { .. }),
        "unexpected probe result on a non-verity file: {probe:?}"
    );

    let guard = Guard::VerityContentIdentity {
        path: path.clone(),
        expected,
        verity: pin(1, &[0x11; 32]),
        executable: false,
    };
    // The pin is fiction, so nothing was proven; the full hash decides, and it matches.
    guard
        .validate(GuardMode::Strict)
        .expect("fallback must accept matching content");

    // The decisive test: a verity guard is never a metadata-only acceptance. Identical metadata,
    // different content, fabricated pin -> refusal.
    let mut file = fs::File::create(&path).expect("reopen");
    file.write_all(b"phase-y CONTENT").expect("rewrite");
    drop(file);
    let failure = guard
        .validate(GuardMode::Strict)
        .expect_err("changed content must not be accepted");
    assert!(
        failure.reason.contains("content changed") || failure.reason.contains("contradicted"),
        "unexpected failure reason: {}",
        failure.reason
    );
}

/// The pair path must apply the same rule: metadata and content are one decision, and a verity half
/// that cannot answer falls back to hashing from the same descriptor.
#[test]
fn a_verity_pair_falls_back_together() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("input.bin");
    let mut file = fs::File::create(&path).expect("create");
    file.write_all(b"pair content").expect("write");
    drop(file);

    let metadata = fingerprint(&path).expect("fingerprint");
    let expected = hash_file(&path).expect("hash");
    let guards = vec![
        Guard::FileMetadata {
            path: path.clone(),
            expected: metadata,
        },
        Guard::VerityContentIdentity {
            path: path.clone(),
            expected,
            verity: pin(2, &[0x22; 64]),
            executable: false,
        },
    ];
    let report = validate_all(&guards, GuardMode::Strict);
    assert!(
        report.failure.is_none(),
        "pair fallback must pass: {report:?}"
    );
    assert_eq!(report.checked, 2);

    // Same metadata, different bytes: the hash half must fail.
    let mut file = fs::File::create(&path).expect("reopen");
    file.write_all(b"pair CONTENT").expect("rewrite");
    drop(file);
    let report = validate_all(&guards, GuardMode::Strict);
    let failure = report.failure.expect("changed content must fail");
    assert!(matches!(
        failure.guard.as_ref(),
        Guard::VerityContentIdentity { .. }
    ));
}

/// A fabricated pin must not become a reason to skip hashing for an *executable* either.
#[test]
fn an_executable_verity_guard_still_checks_permissions() {
    use std::os::unix::fs::PermissionsExt;

    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("tool");
    let mut file = fs::File::create(&path).expect("create");
    file.write_all(b"#!/bin/sh\ntrue\n").expect("write");
    drop(file);
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).expect("chmod");

    let expected = hash_file(&path).expect("hash");
    let guard = Guard::VerityContentIdentity {
        path: path.clone(),
        expected,
        verity: pin(1, &[0x33; 32]),
        executable: true,
    };
    guard
        .validate(GuardMode::Strict)
        .expect("executable content matches");

    fs::set_permissions(&path, fs::Permissions::from_mode(0o644)).expect("chmod");
    let failure = guard
        .validate(GuardMode::Strict)
        .expect_err("a non-executable file must not satisfy an executable guard");
    assert!(
        failure.reason.contains("executable"),
        "unexpected failure reason: {}",
        failure.reason
    );
}

#[test]
fn a_pin_is_only_taken_when_the_kernel_answers() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("input.bin");
    let mut file = fs::File::create(&path).expect("create");
    file.write_all(b"pin me").expect("write");
    drop(file);

    let file = fs::File::open(&path).expect("open");
    let pin = pin_before_read(&file);
    match probe_support(&path) {
        SupportProbe::NotEnabled { .. } | SupportProbe::Supported { .. } => {
            assert!(
                pin.is_some(),
                "a verity-answering kernel must produce a pin"
            )
        }
        SupportProbe::Unsupported { errno } => {
            assert!(
                pin.is_none(),
                "no pin may be invented without a kernel measurement (errno {errno})"
            )
        }
        SupportProbe::Unreadable { ref detail } => panic!("probe failed: {detail}"),
    }
    // Whatever happened, the measurement never modified the file.
    assert_eq!(fs::read(&path).expect("read"), b"pin me");
}

/// `Hash` serializes as 32 decimal bytes; records are built with the real encoder so these tests
/// pin the shipped wire format rather than a guess about it.
fn expected_field() -> String {
    serde_json::to_string(&Hash::new([0; 32])).expect("encode hash")
}

#[test]
fn existing_records_still_decode() {
    // A Phase X record predates this field and carries no verity pin at all.
    let legacy = String::from("{\"FileHash\":{\"path\":\"/usr/bin/cc1\",\"expected\":")
        + &expected_field()
        + "}}";
    let guard: Guard = serde_json::from_str(&legacy).expect("legacy record must decode");
    assert!(matches!(guard, Guard::FileHash { .. }));
    // Round-tripping it must not invent a pin.
    let encoded = serde_json::to_string(&guard).expect("encode");
    assert!(!encoded.contains("verity"), "unexpected field: {encoded}");
}

#[test]
fn a_verity_record_round_trips_its_digest() {
    let guard = Guard::VerityContentIdentity {
        path: "/usr/bin/cc1".into(),
        expected: Hash::new([7; 32]),
        verity: VerityPin::new(1, vec![0xde, 0xad, 0xbe, 0xef]),
        executable: true,
    };
    let encoded = serde_json::to_string(&guard).expect("encode");
    assert!(
        encoded.contains("\"deadbeef\""),
        "unexpected encoding: {encoded}"
    );
    let decoded: Guard = serde_json::from_str(&encoded).expect("decode");
    assert_eq!(decoded, guard);
}

#[test]
fn a_malformed_digest_field_is_rejected() {
    // A corrupted record must not decode into a guard that then silently hashes: the record itself
    // is unservable, and the caller skips the candidate.
    let head = String::from("{\"VerityContentIdentity\":{\"path\":\"/p\",\"expected\":")
        + &expected_field();
    let corrupt =
        head.clone() + ",\"verity\":{\"algorithm\":1,\"digest\":\"zz\"},\"executable\":false}}";
    assert!(serde_json::from_str::<Guard>(&corrupt).is_err());
    let odd = head + ",\"verity\":{\"algorithm\":1,\"digest\":\"abc\"},\"executable\":false}}";
    assert!(serde_json::from_str::<Guard>(&odd).is_err());
}

/// Manual measurement: what one `FS_IOC_MEASURE_VERITY` attempt costs when the kernel cannot
/// answer. Not a correctness test, so it is ignored by default.
///
/// Run with:
///   cargo test --release -p tracejit-guards --lib measure_call_cost -- --ignored --nocapture
#[test]
#[ignore = "manual measurement"]
fn measure_call_cost() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("input.bin");
    let mut file = fs::File::create(&path).expect("create");
    file.write_all(&[0_u8; 1 << 20]).expect("write");
    drop(file);

    let open = fs::File::open(&path).expect("open");
    let rounds = 100_000_u32;
    let started = std::time::Instant::now();
    let mut outcomes = [0_u32; 3];
    for _ in 0..rounds {
        match measure(&open) {
            MeasureOutcome::Measured { .. } => outcomes[0] += 1,
            MeasureOutcome::Unavailable { .. } => outcomes[1] += 1,
            _ => outcomes[2] += 1,
        }
    }
    let elapsed = started.elapsed();
    println!(
        "measure(): {} rounds, {:.1} ns/op, outcomes measured={} unavailable={} other={}",
        rounds,
        elapsed.as_nanos() as f64 / f64::from(rounds),
        outcomes[0],
        outcomes[1],
        outcomes[2]
    );
}
