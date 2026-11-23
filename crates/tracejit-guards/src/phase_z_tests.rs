//! Phase Z regressions: build-independent admission of a runtime's allocator entropy.
//!
//! The audited call site is a property of an instruction sequence, so it can be exercised without
//! owning any particular runtime image. Each test assembles the audited sequence into a synthetic
//! library file, records a guard against that file, and then breaks exactly one thing. The real
//! images are checked by `cargo test -p tracejit-effects -- --ignored
//! audited_sites_match_a_reference_library`, which re-derives the destination from the shipped
//! library's own bytes.

use super::*;
use std::io::Write;

/// The bytes that follow the `syscall`, from the audited profile.
const SIGNATURE: &[u8] = &[0x0f, 0x05, 0x48, 0x8d, 0x5d, 0xd0, 0x48, 0x83, 0xf8, 0x08];
const MOV_EAX_GETRANDOM: [u8; 5] = [0xb8, 0x3e, 0x01, 0x00, 0x00];
const LEA_RDI_RIP: [u8; 3] = [0x48, 0x8d, 0x3d];
const MOV_ESI_LENGTH: [u8; 5] = [0xbe, 0x08, 0x00, 0x00, 0x00];
const MOV_EDX_NONBLOCK: [u8; 5] = [0xba, 0x01, 0x00, 0x00, 0x00];

/// A file that encodes one profile's audited call site, and nothing else.
struct SyntheticRuntime {
    file: tempfile::NamedTempFile,
    build_id: String,
    site_offset: u64,
    destination_offset: u64,
    /// Byte offset of the `lea` that loads the syscall's buffer argument.
    load: usize,
}

impl SyntheticRuntime {
    fn new(profile: &tracejit_effects::AllocatorEntropyProfile) -> Self {
        let syscall = profile.site_offset as usize - 2;
        let number_load = syscall - MOV_EAX_GETRANDOM.len();
        // `mov $1,%edx; mov $8,%esi; lea ...;` — the audited order, with filler before the syscall
        // number so the buffer load is the nearest candidate.
        let load = number_load - 21;
        let mut image = vec![0x90u8; syscall + SIGNATURE.len() + 0x10];
        image[load - 10..load - 5].copy_from_slice(&MOV_EDX_NONBLOCK);
        image[load - 5..load].copy_from_slice(&MOV_ESI_LENGTH);
        image[load..load + 3].copy_from_slice(&LEA_RDI_RIP);
        let displacement = (profile.destination_offset as i64 - (load as i64 + 7)) as i32;
        image[load + 3..load + 7].copy_from_slice(&displacement.to_le_bytes());
        image[number_load..number_load + 5].copy_from_slice(&MOV_EAX_GETRANDOM);
        image[syscall..syscall + SIGNATURE.len()].copy_from_slice(SIGNATURE);
        let mut file = tempfile::NamedTempFile::new().unwrap();
        file.write_all(&image).unwrap();
        file.flush().unwrap();
        Self {
            file,
            build_id: profile.build_id.to_string(),
            site_offset: profile.site_offset,
            destination_offset: profile.destination_offset,
            load,
        }
    }

    fn path(&self) -> &Path {
        self.file.path()
    }

    fn guard(&self) -> Guard {
        Guard::ControlledEntropy {
            library: self.path().to_path_buf(),
            expected: hash_file(self.path()).unwrap(),
            build_id: self.build_id.clone(),
            site_offset: self.site_offset,
            destination_offset: self.destination_offset,
            module_offset: self.site_offset,
            length: 8,
            flags: 1,
            value: tracejit_effects::ALLOCATOR_ENTROPY_VALUE,
            contract: tracejit_effects::ALLOCATOR_ENTROPY_CONTRACT.into(),
        }
    }

    /// Rewrites the buffer load so the library encodes a different destination, then re-hashes.
    ///
    /// The returned file must outlive the guard: it holds the bytes the guard re-reads.
    fn displace_buffer(&self, by: i32) -> (tempfile::NamedTempFile, Guard) {
        let mut image = std::fs::read(self.path()).unwrap();
        let mut displacement =
            i32::from_le_bytes(image[self.load + 3..self.load + 7].try_into().unwrap());
        displacement += by;
        image[self.load + 3..self.load + 7].copy_from_slice(&displacement.to_le_bytes());
        let mut file = tempfile::NamedTempFile::new().unwrap();
        file.write_all(&image).unwrap();
        file.flush().unwrap();
        let mut guard = self.guard();
        if let Guard::ControlledEntropy {
            library, expected, ..
        } = &mut guard
        {
            *library = file.path().to_path_buf();
            *expected = hash_file(file.path()).unwrap();
        }
        (file, guard)
    }
}

fn profiles() -> &'static [tracejit_effects::AllocatorEntropyProfile] {
    tracejit_effects::ALLOCATOR_ENTROPY_PROFILES
}

#[test]
fn a_synthetic_runtime_with_the_audited_sequence_is_admitted() {
    for profile in profiles() {
        let runtime = SyntheticRuntime::new(profile);
        let guard = runtime.guard();
        assert!(
            guard.validate(GuardMode::Strict).is_ok(),
            "{}: {guard:?}",
            profile.build_id
        );
        assert!(
            guard.validate(GuardMode::Fast).is_ok(),
            "{}: {guard:?}",
            profile.build_id
        );
    }
}

#[test]
fn a_runtime_whose_encoded_destination_disagrees_with_its_profile_is_refused() {
    // The build ID and the record's own offsets still match the audited table; only the code the
    // record points at has moved. This is the counterexample class the derived check exists for.
    for profile in profiles() {
        let runtime = SyntheticRuntime::new(profile);
        let (file, guard) = runtime.displace_buffer(8);
        let error = guard.validate(GuardMode::Strict).unwrap_err();
        assert!(file.path().exists());
        assert!(
            error.reason.contains("audited"),
            "{}: {}",
            profile.build_id,
            error.reason
        );
    }
}

#[test]
fn a_record_naming_another_builds_site_is_refused() {
    let all = profiles();
    assert!(
        all.len() >= 2,
        "the audit set should name more than one build"
    );
    let runtime = SyntheticRuntime::new(&all[0]);
    let mut guard = runtime.guard();
    if let Guard::ControlledEntropy {
        build_id,
        site_offset,
        module_offset,
        ..
    } = &mut guard
    {
        *build_id = all[1].build_id.to_string();
        *site_offset = all[1].site_offset;
        *module_offset = all[1].site_offset;
    }
    assert!(guard.validate(GuardMode::Strict).is_err());
}

#[test]
fn a_record_outside_the_audited_table_is_refused() {
    let runtime = SyntheticRuntime::new(&profiles()[0]);
    let mut guard = runtime.guard();
    if let Guard::ControlledEntropy { build_id, .. } = &mut guard {
        *build_id = "00".repeat(20);
    }
    assert!(guard.validate(GuardMode::Strict).is_err());
}

#[test]
fn a_record_from_another_contract_is_refused() {
    let runtime = SyntheticRuntime::new(&profiles()[0]);
    let mut guard = runtime.guard();
    if let Guard::ControlledEntropy { contract, .. } = &mut guard {
        *contract = "tracejit.compiler-runtime.v1".into();
    }
    assert!(guard.validate(GuardMode::Strict).is_err());
}

#[test]
fn a_record_with_a_different_request_shape_is_refused() {
    for (length, flags) in [(8u32, 0i32), (16, 1), (4, 1)] {
        let runtime = SyntheticRuntime::new(&profiles()[0]);
        let mut guard = runtime.guard();
        if let Guard::ControlledEntropy {
            length: guard_length,
            flags: guard_flags,
            ..
        } = &mut guard
        {
            *guard_length = length;
            *guard_flags = flags;
        }
        assert!(
            guard.validate(GuardMode::Strict).is_err(),
            "{length} bytes, flags {flags}"
        );
    }
}

#[test]
fn a_record_with_a_destination_the_library_does_not_encode_is_refused() {
    let runtime = SyntheticRuntime::new(&profiles()[0]);
    let mut guard = runtime.guard();
    if let Guard::ControlledEntropy {
        destination_offset, ..
    } = &mut guard
    {
        *destination_offset += 0x10;
    }
    assert!(guard.validate(GuardMode::Strict).is_err());
}

#[test]
fn a_record_with_a_changed_runtime_library_is_refused() {
    let runtime = SyntheticRuntime::new(&profiles()[0]);
    let mut guard = runtime.guard();
    if let Guard::ControlledEntropy { expected, .. } = &mut guard {
        *expected = canonical_hash(&"a different runtime").unwrap();
    }
    assert!(guard.validate(GuardMode::Strict).is_err());
}

#[test]
fn a_record_with_a_value_the_contract_did_not_supply_is_refused() {
    for value in [tracejit_effects::ALLOCATOR_ENTROPY_VALUE ^ 1, 0, u64::MAX] {
        let runtime = SyntheticRuntime::new(&profiles()[0]);
        let mut guard = runtime.guard();
        if let Guard::ControlledEntropy {
            value: recorded, ..
        } = &mut guard
        {
            *recorded = value;
        }
        assert!(guard.validate(GuardMode::Strict).is_err(), "{value:#x}");
    }
}

#[test]
fn every_audited_profile_names_a_distinct_build_and_site() {
    let all = profiles();
    for (index, profile) in all.iter().enumerate() {
        assert!(
            all[index + 1..]
                .iter()
                .all(|other| other.build_id != profile.build_id),
            "duplicate build id {}",
            profile.build_id
        );
        assert_eq!(profile.site_signature, SIGNATURE);
        // The destination is `tcache_key` in both audited builds. A profile that changed it would
        // need a new audit argument, not a silent edit.
        assert_eq!(profile.destination_offset, 0x20b178);
    }
}
