# Online Courses Dashboard design adaptation

Reference supplied by the user: **FREE - Online Courses Dashboard by Bogusław Podhalicz.pdf**, one page, 1440 × 900 points. PDF SHA-256: `1a1b53bc19c2884e4bc67783c418bc6a2e4c87a93ac1cb586af201a81c79a6eb`.

The Figma connector could not access the source file. Implementation uses the subsequently supplied PDF. The reference has one desktop dashboard; other screens and responsive states extend its visual language. Its sample people, course ratings, learning hours and subscription price are not represented as Northstar data.

## Design and assets

- Floating black rail, white canvas, light grey cards, rounded corners, outlined secondary buttons and black primary buttons.
- Rounded Baloo Bhai 2 headings and Roboto body text, locally hosted with their SIL Open Font Licenses from the Google Fonts repository.
- Welcome and book illustrations extracted from the original PDF at 3× resolution; no generated replacement artwork.
- Existing Northstar brand and functional navigation remain available. The rail expands into labelled navigation and becomes a dialog on mobile.
- Workspace branding stays configurable. New workspace defaults use black and grey; the current workspace palette was aligned through the existing settings API.

## Screen coverage

| Area | Application |
| --- | --- |
| Overview | Greeting, agent carousel, filterable agent rows, live analytics, chart metric/period controls, inbox and learning card |
| Education overview | Course carousel and rows, active/archived/newest filters, enrollment totals, real course/enrollment creation chart, all academy tools |
| Education operations | Courses, batches, students, student detail, enrollments, imports, access requests, activity, forms and dialogs |
| Agents | Cards and list, creation, purpose/status controls, instructions, knowledge, settings and deployment |
| Integrations / CRM | Catalog, connection dialogs, advanced management, mapping, routing, operations and workflow controls |
| Conversations / leads | Independent scrolling panes, human replies, visitor editor, lead fields, export/import and CRM sync controls |
| Workspace | Account, team, billing, API keys, preferences, white label and platform administration |
| Help | Categories, search, article content, assistant, support and request detail |
| Authentication | Login, registration, password reset, verification, MFA, invitations and education recovery |
| Common states | Loading, empty, error/retry, disabled, focus, confirmation, notifications, command search and toasts |

Public customer widgets and WhatsApp previews continue to show the bot's configured channel appearance. Platform styling does not replace customer-selected widget colors or claim control over WhatsApp's interface.

## Implementation

`frontend/src/theme/academy.tokens.css` and `academy.css` load after the existing structural styles. Shared dashboard primitives are in `components/academy-dashboard.tsx`. Desktop, tablet and mobile layouts use the same routes, permissions and APIs. Data tables retain horizontal scrolling; the inbox retains independent message/list scrolling.

The dashboard controls have regression coverage in `pages/AcademyDashboards.test.tsx`. Browser audit artifacts and comparison screenshots are saved locally under `reports/academy/`.

## Validation

- Production TypeScript and Vite build passed; deployed Docker services passed their readiness checks.
- 43 focused frontend tests passed across the dashboards, shared shell, education layout, courses, agent builder, WhatsApp deployment and branding.
- Live WhatsApp deployment checks passed for welcome/reply settings saved and reloaded, failed-save recovery, blocked activation without a number, real chat links, clipboard copy and PNG/SVG QR downloads. A temporary draft bot was removed after testing; the existing active CMA bot, its number and its settings were preserved. This does not claim a new live customer-message delivery test.
- 35 signed-in pages passed browser checks at 1440, 1024 and 390 pixels (105 page/viewport checks), with no document overflow or browser errors. Nine public authentication/recovery/error routes were also checked at desktop and mobile sizes. Interaction checks cover navigation, editable dialogs and independent conversation scrolling. Mobile education tables retain their own horizontal scrollbar without widening the page.
- The broader suite is not green: 27 frontend failures also reproduce on the unchanged baseline commit `8d15673`. The additional WhatsApp enhancer failure from the first full run passed when rerun in the focused set. Both workspace backend tests also fail on that baseline (starter-plan white-label restriction and secondary-workspace fixture setup). These failures are not reported as passing validation.
