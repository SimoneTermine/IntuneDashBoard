---
name: review-device-collector
description: Review a Microsoft Graph collector using the repository's read-only reviewer.
argument-hint: Enter a collector file to review
agent: Graph Collector Reviewer
---

Review this collector: ${input:collector:app/collector/devices.py}

Follow the repository instructions and the graph-collector-review skill. Trace the collector through its callers, GraphClient requests, endpoint constants, pagination, error handling, and database writes.

Report evidence-based findings, separating confirmed issues from risks or questions. Keep the review read-only: do not edit files or run commands.