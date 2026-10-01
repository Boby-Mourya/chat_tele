# MaterialM frontend validation - September 14, 2026

## Design source

User-uploaded `MaterialM Free Tailwind React Admin Template.zip`, SHA-256 `fb50fc18ccfa6adbed457c9c244a4e4b28dd94203ece05634b6ad1f1fc663429`. Source files and hashes are recorded in `MATERIALM_SOURCE_PROVENANCE.json`.

## Executed checks

- Production TypeScript/Vite build and Docker frontend image build passed. Vite reports the existing large JavaScript bundle warning.
- 45 Vitest tests passed across MaterialM shell, Education layout, navigation permissions, command palette, login/MFA, signup, and agent management.
- Three backend analytics integration tests passed with startup help-content indexing disabled in the test process (`HELP_CONTENT_SYNC_ON_STARTUP=false`). They cover selected periods, domain metrics, workspace isolation, and deleted agents.
- ESLint passed for the changed frontend TypeScript files; Ruff passed for the analytics/workspace routers.
- Chromium checked 16 authenticated routes at 1440, 768, 390, and 320px: overview, agents, conversations, leads, education hub, courses, students, enrollments, integrations, CRM workflow, analytics, audit, deploy, workspace, white-label, and help.
- Additional checks cover expanded integration forms, agent list view, six authentication/recovery routes at desktop and phone widths, mobile drawer navigation, command search, and a real 7-to-30-day analytics period change.
- Browser checks found no JavaScript page errors. The workspace owner correctly receives 403 from the platform-admin access probe; no other HTTP failures occurred in the final authenticated sweep.
- Narrow-screen issues found during validation were corrected: agent badges, integration forms, account recovery buttons, analytics chart and question rows. Tables and deployment tabs retain local horizontal scrolling where needed.
- Final Docker image verification passed 30 additional viewport checks. Analytics accepts 7, 30, and 90 days (200) and rejects an unsupported 8-day period (422). Results are appended under `finalImageRechecks` in the browser report.

## Local runtime and evidence

Frontend: http://localhost:3100. Backend: http://localhost:8100. Docker project: `northstar-chat-check`; web/API and infrastructure with health checks report healthy.

Local, ignored artifacts under `reports/`: `materialm-validation.json`, `materialm-overview-1440.png`, `materialm-overview-390.png`, route screenshots, authentication screenshots, and browser scripts. Docker build log: `.git/materialm-web-build.log`.

The checks exercise the running application with its local database. External CRM authorization and AI model calls require their configured provider credentials and are outside this visual alignment validation.
