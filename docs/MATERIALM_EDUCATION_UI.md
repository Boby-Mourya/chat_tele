# MaterialM frontend and unified Education workspace

Branch: `feature/materialm-education-hub`
Original base: `c9227ed9de2e3c9fee9d0557a9916e8f6feb466b`.
Updated main incorporated: `609858a386f170065a65f7f5aeee37251c58ada3`.
Original scope: frontend layout/navigation adaptation. The branches have since been merged into main. See the September 2026 alignment update below.

## Implementation

The supplied MaterialM template's 256px sidebar, grouped navigation, pill-shaped links, header, 12px cards, spacing and color tokens are adapted to the existing Northstar React app. `materialm.tokens.css` contains the supplied palette, scoped to the authenticated shell. The application does not import the template's global Tailwind reset, demo dashboards, advertising links, authentication demos or React 19 dependency tree. The existing React stack, real screens and API clients remain in use. This is a compatibility adaptation of MaterialM, not a replacement of Northstar with the template demo.

- `MaterialmAppShell.tsx`: authenticated layout, responsive navigation dialog, account menu, notifications, command search and workspace-keyed page reset.
- `WorkspaceSwitcher.tsx`: existing WorkspaceProvider callbacks, create/switch controls, error handling and bounded form fields.
- `MaterialmSidebar.tsx`: one route registry for desktop and mobile, grouped captions, one Education entry.
- `materialm-navigation.ts`: primary/Education navigation, longest matching child route, permission-based visibility and command labels.
- `EducationLayout.tsx`: persistent Education navigation and UI permission checks around the existing pages.
- `EducationHubPage.tsx`: navigation launchpad; no demo statistics, new API calls, contact conversion or CRM actions.
- `App.tsx`: selects the new shell and nests the existing Education routes without changing their URLs. The old `app-shell.tsx` remains available for comparison/rollback.

## Navigation

Workspace: Overview, Agents.
Engagement: Conversations, Leads, Integrations.
Learning: Education.
Operations: Analytics, Audit, Deploy.
Existing Workspace settings and Help Center remain available.

Education opens `/education`, with Overview, Students, Courses, Batches, Enrollments, Imports, Access requests and Activity in one area. Student detail remains `/education/students/:studentId`; Imports remains `/education/students/import` and selects Imports, not Students. Student conversation/history tools remain in the existing detail/activity pages. The standalone public `/education-access-recovery` URL is preserved outside the authenticated layout. No unimplemented education inbox endpoint is invented.

## Business-policy scope

The supplied updated flow is the design authority: Lead Generation and General/Support use CRM; Education has no Lead/CRM link or optional upsell exception. This delivery separates the navigation and introduces no Education-to-CRM actions. It does not claim that grouping pages enforces server-side data isolation. Existing backend purpose enforcement, old upsell settings, queued-job lineage and Support-to-CRM behavior have not been changed or certified by this frontend-only patch. They need their own backend regression evidence for the revised policy.

The newer main branch added the Zoho one-click integration and `IntegrationsHubPage`; those changes are incorporated and preserved here, including the deployment migration-head fixes. This frontend change does not separately apply the earlier CRM ZIP. No live provider test or new CRM write is performed by the Education hub.

## Pull into an isolated worktree

From an existing clean Chat checkout:

```bash
git fetch origin
git worktree add ../Chat-materialm --track -b materialm-ui-test origin/feature/materialm-education-hub
cd ../Chat-materialm
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

The worktree keeps the original checkout on its current branch. Do not run the worktree command again with the same directory or local branch name.

## Run against a local development backend

The existing Vite proxy sends `/api` to `http://localhost:8000`. Use a development/test backend and test workspace, not production data. Disable demo fallbacks when checking real integrations.

PowerShell:

```powershell
$env:VITE_DEMO_MODE = "false"
$env:VITE_API_URL = "/api/v1"
$env:VITE_DEV_API_URL = "http://localhost:8000"
npm run dev
```

Linux/macOS:

```bash
VITE_DEMO_MODE=false VITE_API_URL=/api/v1 VITE_DEV_API_URL=http://localhost:8000 npm run dev
```

Open `http://localhost:5173`. Set `VITE_DEV_API_URL` to the actual test backend address as needed. Authentication and authorization still use the existing backend. Opening the UI does not provision provider credentials or migrate the database.

## Acceptance checks

1. Sign in through existing login/MFA and open Education. Confirm every existing Education section and student-detail deep link works after browser refresh.
2. Change workspaces. Confirm the existing provider changes scope and remounts the active page; inspect `X-Workspace-ID` in API requests.
3. At narrow widths, open navigation, visit Education and Integrations, close with Escape/backdrop and verify focus returns. Check all destinations remain reachable.
4. Collapse/expand the desktop sidebar and reload. Search for `Education / Imports` using Ctrl/Cmd+K.
5. Check view-only and management permissions, including direct import URLs. The API, not the sidebar, remains authoritative.
6. Confirm existing Lead/CRM, channel configuration, deployment, team, billing, white-label and Help screens still operate against the test backend.

## Validation boundaries

Local executable checks: TypeScript/TSX syntax, PostCSS parsing, pure navigation tests, strict typecheck of the standalone navigation module, and route/source contracts. The changes include Vitest/Testing Library regression tests for hub navigation, permission handling, mobile destinations, workspace switching, sidebar persistence and account controls.

A full repository dependency install, browser render, complete frontend test run and production build are not claimed by those local checks. The local runtime cannot resolve GitHub/npm hosts or clone/install the private repository. The branch PR invokes the existing repository CI; inspect its actual result before treating this as a release. Keep main unchanged while testing.

## September 2026 alignment update

The uploaded ZIP was inspected again and its SHA-256 matches the provenance record. The authenticated application and authentication pages now share the supplied MaterialM design: local Inter variable font, cyan/turquoise defaults, 256px sidebar, pill navigation and buttons, 12px CardBox corners, 30px gutters, and a centered 1200px content container. The dashboard uses the template's eight/four-column layout with live conversation reports and agent statistics. Login and registration use the template's centered white card and pastel gradient.

`frontend/src/theme/materialm.components.css` maps the template's components to the existing application controls. Theme imports are placed after legacy styles in `main.tsx` so the intended design wins consistently. Embedded customer chat styling and saved custom workspace colors are preserved. Default workspace colors now match MaterialM in both frontend and backend. Navigation becomes a keyboard-accessible drawer below 1280px. Narrow forms wrap; wide tables and deployment tabs scroll within their own sections.

The overview period selector now fetches its chosen period and displays the returned date labels. The analytics query parser was corrected to accept the supported integer periods over HTTP; previously explicit periods returned 422. Loading, error, and empty chart states no longer draw fabricated chart values.

The source archive is a design reference, not operational instructions. Template advertising, sample sales data, and fake authentication handlers are not application features.
