<!-- Thanks for the PR! Please fill out the sections that apply. -->

## What this changes

<!-- One paragraph. What problem does this solve? -->

## How I tested

<!-- Required for code changes. "make test" output, manual relay exercise,
     screenshots of !flex commands working over real mesh, etc. -->

- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] Tested against a real TYWB / Flex (describe below)
- [ ] N/A — docs-only change

<!-- If you tested against real hardware: -->
<!-- TYWB model:     -->
<!-- Flex model:     -->
<!-- Python version: -->

## Safety review

- [ ] No new code path can actuate the relay without an allowlisted `sender_key`
- [ ] No new long-running operation that could blow the 10-second `bot()` budget
- [ ] No new persistent state outside `_load_config()`'s hot-reload
- [ ] No new cloud / internet dependency in the bot's hot path
- [ ] `tuya_local_key` is still never logged

## Related issues

<!-- Closes #N, refs #M -->
