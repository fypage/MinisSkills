# GRSAI Optional Backend Audit (2026-07-17)

Source artifact: `grsai-image-generate.zip`

SHA256: `f4e0af6f59dccd644022df839e6aadc4c137ecd3be0e1a74ab12fcad5171a703`

## Useful parts

- Direct API wrapper supports GPT Image and Nano Banana model families.
- Local reference-to-data-URI conversion.
- Image compression helper.
- Interactive local mask painter for selective edits.
- Result download into `/var/minis/attachments`.

## Do not merge unchanged

- Requires a separate `GRSAI_API_KEY`; none was configured during audit.
- Defaults to a vendor-specific VIP model and 2048×2048, which can be costly and timeout-prone.
- Sync/async behavior is hard-coded from anecdotal observations and may become stale.
- The inpaint workflow automatically uploads original images and masks to public temporary hosts. This violates the main skill's local-reference default and must be explicit opt-in.
- Missing strong download validation: URL scheme/host policy, content type, byte limit, image decode, pixel limits, redirect limits, and SSRF controls.
- Temporary state uses global `/tmp` filenames, causing cross-task collisions.
- Background server lifecycle and child-process cleanup are incomplete.
- `imghdr` is deprecated/removed in newer Python versions.
- API errors call `sys.exit` deep inside helpers, reducing structured diagnostics and testability.

## Adoption recommendation

Keep GRSAI as a separate optional skill/provider rather than coupling it to the provider-neutral OpenMinis wrapper. Before installation:

1. Require `GRSAI_API_KEY` via Settings, never chat.
2. Default to 1K / one image / conservative model.
3. Keep local data URI references by default.
4. Make public upload an explicit `--allow-public-upload` action with user consent.
5. Use per-case state directories instead of shared `/tmp` names.
6. Validate all downloaded outputs and cap bytes/pixels.
7. Add dry-run payload tests and mocked HTTP tests.
