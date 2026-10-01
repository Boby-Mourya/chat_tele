# WhatsApp inbox and sender details

The current frontend uses a WhatsApp-specific conversation view: white incoming customer messages on the left, pale green business replies on the right, message timestamps, date separators, a compact composer, and locally served third-party logos. Enter sends; Shift+Enter inserts a new line. The existing approved-template flow remains available.

## Live data

The inbox refreshes every two seconds while visible, and refreshes on focus or reconnection. It keeps unsent drafts and preserves the reading position when the operator scrolls up. Updates use polling, not a WebSocket.

Delivery indicators come from stored Meta delivery receipts and durable delivery jobs. Pending replies show a clock, accepted replies one tick, delivered replies two ticks, and read replies blue ticks. Failed replies are marked explicitly. Messages without delivery evidence have no ticks. Split replies require delivery/read evidence for every part. Provider receipts are matched to the exact message and connection; AI replies use the inbound idempotency key and the assistant sequence reserved by the chat coordinator.

## Sender details

`ConversationOut.whatsappContact` exposes the phone number in international format, WhatsApp ID, supplied profile name, latest incoming-message time, and message type. These come from signed incoming message records within the authorized conversation scope. Both regular and education conversation lists expose the same information.

Existing conversations receive these fields from their saved inbound records without a database reset or migration. New messages also populate an empty `visitor_details.phone`. Manually saved contact information is preserved. Provider identity is shown separately from editable visitor details.

The contact panel is visible on desktop and accessible through **Contact details** on smaller screens. WhatsApp does not automatically supply the sender's email, location, IP address, or profile photograph; the interface does not fabricate these fields.

## Assets and verification

Logo sources and notices are in `frontend/public/brands/README.md`. The app serves these assets locally rather than relying on remote image requests.

Focused verification covers sender mapping, older conversations, manual field preservation, split delivery receipts, message direction, status refresh, draft preservation, composer keyboard behavior, template sending UI, and integration configuration. Runtime checks use local authenticated read-only requests and browser screenshots. Public ngrok checks do not submit stored credentials.

On 2026-09-15, 45 focused frontend tests and 57 backend tests passed, along with the frontend production build, new-component lint checks, and targeted Python lint checks. Local runtime verification found sender details on all four WhatsApp conversations in the selected workspace and provider-backed read receipts on the selected conversation. These are focused checks; they do not claim that the entire repository test suite passes.
