# Bot enrollment and WhatsApp setup

Open **AI agents**. Each card has an Active switch. Switching off saves the bot as a draft and pauses new replies; students, enrollments, knowledge and number assignments are retained. An Education bot needs at least one active student/course/batch enrollment before activation. A WhatsApp bot also needs a connected number and webhook. Message-time student identity, enrollment dates and course access checks still apply.

Choose **Manage enrollments** on an education bot. The page selects that bot, shows its number and setup checks, and filters its enrollment directory. Use **Add enrollment** for an existing student; the bot is preselected. Student WhatsApp numbers are managed and verified in Education > Students. Verify only after confirming ownership of the student's number.

## Bulk enrollment

1. Select the bot, active course and batch.
2. Download **Enrollment CSV**, replace the example row, and add up to 500 students.
3. Keep phone cells as text with a `+` country code. Set `identity_type` to `whatsapp`; `identifier` contains the student number. `identity_verified=false` leaves identity verification pending. Mark it true only after verification. Preserve unique, stable `student_id` values.
4. Upload CSV or Excel (`.xlsx`, maximum 2 MB), inspect row errors/warnings, then click **Enroll students**. The selected bot/course/batch is used for all rows. Supplied dates must fit the batch; missing dates use its bounds.
5. Any invalid row blocks the entire import. Existing student IDs are rejected, preventing duplicates; add their new enrollment through **Add enrollment**. Draft education bots can receive enrollments and be activated afterwards.

## Automatic enrollment after payment and LMS access

Select **Automatic enrollment API** to copy the public endpoint and the JSON request for the chosen bot/course/batch. Its address is:

`POST /api/v1/education/agents/{agent_uuid}/enrollment-events`

Create a server credential in **Workspace > API keys** using an account with education management permission. Send it in `Authorization: Bearer YOUR_WORKSPACE_API_KEY` and use `Content-Type: application/json`. The key is workspace-scoped, revocable, and must stay on the sending server.

Configure the CRM/LMS workflow to call this endpoint on the transition where payment is confirmed **and** LMS access is granted. It accepts a provider-neutral JSON body; native provider webhook bodies must be mapped to this contract by the CRM workflow or your server. Payment is attested by the authenticated sending system; this app does not independently query a payment gateway or grant access in the external LMS.

```json
{
  "eventId": "payment-ORDER-001-access-granted",
  "source": "your-lms",
  "paymentStatus": "paid",
  "accessGranted": true,
  "paymentReference": "ORDER-001",
  "consent": false,
  "row": {
    "studentNumber": "STUDENT-001",
    "name": "Student Name",
    "email": "student@example.com",
    "identityType": "whatsapp",
    "identifier": "+919876543210",
    "identityVerified": false,
    "courseCode": "YOUR-COURSE",
    "batchCode": "YOUR-BATCH",
    "agentPublicId": "COPY_FROM_THE_SETUP_SCREEN",
    "enrollmentStatus": "active"
  }
}
```

Set `identityVerified` to true only if the source system has verified the student's WhatsApp number. With false, the enrollment is created but WhatsApp course access remains blocked until staff verifies the identity. Include optional `startsOn` and `endsOn` dates and scalar `customFields` as needed. Existing access limits are preserved when dates are omitted.

Successful processing atomically creates or updates the student, WhatsApp identity, bot enrollment and a lead, then queues CRM sync. Repeated events with the same workspace/bot/source/event ID and body return the original IDs with `duplicate=true`. Reusing an event ID with changed data returns 409. New events for the same enrollment reuse its lead. Suspended, revoked, expired or graduated enrollments and revoked identities require manual review and cannot be reactivated by this endpoint. An existing student's different WhatsApp number requires staff review.

Use stable student IDs across systems. Trigger only on the payment/access transition, not on every CRM record update, to avoid a feedback loop. Retry timeouts and transient errors with the same event ID; fix 4xx errors before retrying. `GET` on the same endpoint lists the latest 25 accepted receipts. `GET .../readiness` shows bot setup checks and the configured public endpoint.

## CRM delivery and student answers

The event response's `crmSync: queued` acknowledges local sync work, not delivery to a provider. In **CRM workflow**, enable routing for the education bot/API source and map `customFields.student_number`, `course_code`, `batch_code`, `enrollment_id`, `payment_status`, `payment_reference`, `lms_access_granted`, and other needed fields to real provider field names. Configure OAuth and validate the mapping. In **Leads > View sync**, check the provider response/external record ID.

The standard `qualificationReason` mapping also includes a readable payment/enrollment summary. With the default Zoho mapping, this goes into the Lead Description, so the course, batch, bot and payment reference are included even before dedicated custom CRM fields are configured.

For actual WhatsApp answers, keep the bot active, verify the student's identity, keep its enrollment/course/batch active and in date, add and train course-scoped knowledge, and configure the deployment's AI provider. Active status alone does not complete those steps.
