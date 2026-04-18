# Decisions

## [2026-04-19] Architectural decisions confirmed
- QA 5 hard gates: serial, any FAIL = overall FAIL
- Version management: file copy + DB record (not git)
- Knowledge base search: SQL LIKE (no vectors)
- Revision lookup: Python dict hardcoded + string 'in' match
- ASIN ranking / image change detection: manual record only (no auto-scrape)
