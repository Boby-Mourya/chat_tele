# Frontend design and quality review

Reviewed against `4f80baf` on 2026-09-15. The existing academy design remains the
application's visual language: black navigation and primary actions, white
canvas, grey cards, rounded controls, and shared heading/body fonts.

## Changes

- Centralized semantic colors and defined the previously missing CRM, education,
  command-search and account theme aliases in `academy.tokens.css`.
- Added `academy.components.css` for consistent interaction states, form controls,
  alerts, inbox typography, avatars, notification colors, and chart legends.
  Success, warning and error states retain distinct, muted colors.
- Improved keyboard focus visibility on the black navigation rail, input borders,
  reduced-motion behavior, mobile input sizing, and narrow layouts. The analytics
  period selector remains available on mobile.
- Shared fields associate direct native inputs with labels, hints and validation
  errors automatically. Fields containing custom/wrapped controls should continue
  supplying `htmlFor`, input IDs and descriptions explicitly.
- Workspace dashboard branding selects readable black or white primary-button
  text. Hover colors retain that contrast. Customer channel previews keep their
  configured appearance.
- Analytics channel segments now reflect the API proportions, use matching legend
  colors, expose a text description, and display an empty state when appropriate.
  Zero-height bars no longer imply activity where there is none.
- Pages load on demand with accessible loading feedback. Error boundaries preserve
  the application shell and provide recovery actions if a page fails to load.
  Load the Inter font with the customer widget instead of on every application page.

## Validation

| Check | Result |
| --- | --- |
| TypeScript and production build | Passed; no oversized chunk warning |
| Main JavaScript asset | 950.66 KB to 279.93 KB, before compression; this excludes separately loaded page/shared chunks |
| Lint for updated functional components and new tests | Passed |
| Repository-wide frontend lint | 43 errors and one warning; baseline: 45 errors and one warning |
| Focused tests | 63 passed across 12 files |
| Full suite | 395 passed, 26 failed; the baseline had 377 passed, 27 failed |
| Signed-in route audit | 35 pages at 1440, 1024 and 390 px: 105 checks, no document overflow or browser errors |
| Production theme audit | 12 routes at 1440, 1024, 390 and 320 px: 48 checks passed |
| Public routes and interactions | Nine authentication/recovery/error routes at desktop/mobile; navigation, editable dialogs, filters, deep links and independent inbox scrolling passed |
| Production failure recovery | Aborted an analytics page download; recovery screen appeared, navigation remained usable, and opening Agents recovered successfully |

The full suite is **not green**. Remaining failures concern existing billing
expectations, demo/auth API contracts, education and platform selectors, help/team
fixtures, and WhatsApp integration mocks. The baseline lint run also had 45 errors
and one warning, primarily existing hook rules. This review does not certify the
whole application for release or replace backend/integration acceptance testing.

Local browser screenshots and detailed outputs are under `reports/academy/`,
`reports/frontend-theme/`, and `reports/frontend-recovery/` (Git-ignored).

## Reproduce the browser checks

Run the frontend with its API proxy pointed at an available local API, or use a
production preview. Supply `AUDIT_EMAIL` and `AUDIT_PASSWORD` in the environment,
then run:

```powershell
backend/.venv/Scripts/python.exe scripts/audit-frontend-theme.py --base-url http://127.0.0.1:5177
```

For the existing local seed setup, `--env-file .env.launch` is supported. The audit
signs in and reads pages without changing business records. The optional
`--widths 1440,390` flag limits viewport coverage. The failed-download check runs
when production assets are detected.
