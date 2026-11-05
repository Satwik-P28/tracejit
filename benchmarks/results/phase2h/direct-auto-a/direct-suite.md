# Direct-execution compatibility suite

Workloads: 16 (denominator fixed; refusals stay in it)
Reused on the second run: 0/16
Traced output matched a direct run: 16/16

## gzip
- classification Unknown, eligible False, reused False, second decision Executed
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## bzip2
- classification Unknown, eligible False, reused False, second decision Executed
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## xz
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## tar
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## sed
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## grep
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## sort
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## tr
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## base64
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## md5sum
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## wc
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## jq
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## python-json
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## gcc-compile
- classification Unknown, eligible False, reused False, second decision Ineligible
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## assemble
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

## strip
- classification Unknown, eligible False, reused False, second decision Skipped
- direct exit 0, traced exit 0, stdout matches True
- reasons: admission policy is measuring this command before deciding whether to cache

