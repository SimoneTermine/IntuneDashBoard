---
name: graph-collector-review
description: graph-collector-review
disable-model-invocation: true
---
Review the specified Microsoft Graph collector in this repository. Do not modify files unless I explicitly ask you to make changes.

## Scope

Collector to review: [specify a collector or file]

Inspect the relevant code and callers. Trace the runtime call path from the sync engine through the collector to the `GraphClient` methods it invokes.

## Review checklist

- Identify the files and methods involved in the call path.
- Check whether Graph endpoint paths use constants from `app/graph/endpoints.py`.
- Verify the API version passed to each request against the endpoint’s usage and existing code. Do not assume v1.0 or beta; confirm it.
- For collection requests, check whether pagination is required and whether the collector uses the shared paging helper correctly. For report or other non-collection responses, do not assume `get_paged()` applies.
- Review relevant request and collector error handling, including whether exceptions propagate, are caught, or affect sync results.
- Where the collector persists results, trace the database writes and transaction/session conventions.

## Findings and evidence

For every finding, cite the source file and method (include line links when available). Separate:

- **Confirmed issues:** directly demonstrated by inspected code.
- **Risks or questions:** concerns that require API documentation, runtime behavior, or other evidence not present in the repository.

Do not infer behavior from comments or names alone. State when the code does not establish an answer. Do not include tenant data, credentials, tokens, or real identifiers; use synthetic examples only.

Summarize any differences from project conventions and, if there are confirmed issues, propose a focused correction without applying it.