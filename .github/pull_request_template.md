<!--
Title: what changed, in plain words. "Area: change" when it helps (e.g. "Reports: drop the seven old reports, keep four").
Every claim must be checkable: name files, functions, migrations, testids, counts. No adjectives, no restating the diff.
Delete any optional section that has nothing in it.
-->

<!-- One or two sentences: what this does and why. Link the plan doc if there is one (docs/…). -->

<!-- If stacked: "Stacked on #N. Retarget to `develop` once it merges." -->

## Changes

<!-- Grouped by area. Lead each item with the user-visible effect, then the code (`path::name`). A table works for before/after or commit-by-commit. -->

-

## Behaviour changes

<!-- Optional. Anything an existing user or caller will notice: figures, URLs, permissions, refusals, JSON shapes. Write "None." if a refactor. -->

## Migrations

<!-- Optional. Each migration by name, whether it is reversible, what a data migration refuses or rewrites, and the rollback command. -->

## Compatibility

<!-- Optional. Export format version, `api-client/` (regenerated or hand-patched), settings/env vars added, Celery schedules. -->

## Needs the owner

<!-- Optional. Actions outside the repo: dashboards, secrets, production settings, decisions still open. -->

## Not in this PR

<!-- Optional. Scope deliberately left out, and why. -->

## Tests

<!-- Exact results, and what was NOT run. E.g. "Backend: 2,138 tests, OK (`settings_test`)." / "E2E: test_bank_feed, test_budget — 61 passed; other files not run." -->

- Backend:
- E2E:
- New:
- Build: <!-- `vite build`, `tsc`, `makemigrations --check` -->

<!--
Before requesting review:
- New book URLs are classified in apps/books/tests/test_isolation.py
- CLAUDE.md "Recent Changes" has an entry
- api-client/ regenerated if the API schema changed
- Browser-checked at 390px and in dark mode if the UI changed
-->
