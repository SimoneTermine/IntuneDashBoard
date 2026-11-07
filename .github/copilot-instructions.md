# Copilot instructions

- This is a Python 3.10+ desktop application built with PySide6. `main.py` starts the app; `app/ui/` contains the window, pages, widgets, and workers. `app/collector/` coordinates Intune data sync, `app/graph/` handles Microsoft Graph, `app/db/` defines persistence, and `app/analytics/` provides data access for the UI.
- Before describing or changing behavior, inspect the relevant implementation and its callers. Treat names, comments, and README descriptions as clues—not proof of runtime behavior.
- Use the existing `GraphClient` conventions for Graph requests. Use its paging helper for paged collections and follow the endpoint’s existing API-version choice; some endpoints use beta.
- Persist database changes through the existing SQLAlchemy session conventions, including `session_scope()` where appropriate. Preserve compatibility with existing SQLite data; review models and database migrations before changing schemas.
- Keep existing interfaces and signal contracts compatible, or update every consumer and relevant test when a change requires an interface change.
- Add or update tests for behavior changes. Verified test commands include `pytest tests/`, `python -m pytest tests/test_intune_links.py -v`, and `python tests/test_intune_links.py`.
- Never expose, log, or commit credentials, tokens, tenant identifiers, or tenant data. Use synthetic values in tests and examples.
