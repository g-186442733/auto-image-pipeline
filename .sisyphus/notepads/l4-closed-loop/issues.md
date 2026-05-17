# Issues & Gotchas

## [2026-04-19] Known schema issues (to fix in Task 0)
- APlusContent: missing `layout` field, `module_type` has no enum constraint
- TagAssignment: missing `tag_layer` field, no unique constraint
- ImageSlot: deprecated, only referenced in 2 test files (Task 17 cleanup)
