**Table: Adversarial and negative results, including the counterexamples that are kept rather than removed.**

| Class | Case | Observed decision | Observation | Verdict |
| --- | --- | --- | --- | --- |
| Validation-to-restore race | before_validation | Executed | detected before exposure | expected |
| Validation-to-restore race | before_load | Executed | detected before exposure | expected |
| Validation-to-restore race | reverted_mutation | Executed | detected before exposure | see report |
| Validation-to-restore race | after_validation_before_apply | Reused | stale bytes served | documented counterexample |
| Validation-to-restore race | during_hashing | Executed | 8/8 concurrent-writer trials deoptimised | holds under concurrent writes |
| Cached-object corruption | one CAS object corrupted, then reuse attempted | Executed | re-executed, no hit | correct |
| Output timestamp | restored object older than the archive built from it | 2/4 projects reproduced a stale member | make treats the archive as up to date | known limitation |
| Metadata-only observation | mtime/atime/counterexample matrix | 9 cases, 0 incorrect hits | every case matches a native observation | known limitation |

*Source: benchmarks/results/phaseae/toctou_race.json, benchmarks/results/phaseae/tracejit_integrity.json, benchmarks/results/phaseac/stale_archive.json, benchmarks/results/phaseac/metadata_guards.json*
