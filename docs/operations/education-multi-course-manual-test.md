# Multi-course Education Agent: manual setup and test runbook

This runbook verifies that one WhatsApp number can serve several courses while every teaching turn remains restricted to one authorized enrollment, curriculum, batch, and optional paper.

## 1. Start the application

1. Set `EDUCATION_MULTI_COURSE_ENABLED=true` in `.env.launch` (or the environment file used by the stack).
2. Configure the Meta and model variables described in `WHATSAPP_SETUP.md`. Never place Meta secrets in a `VITE_*` variable.
3. Start with `start.bat` from the repository root. Do not use `-NoBuild` after changing this implementation.
4. Confirm the API reports ready and sign in using the configured seed administrator account.
5. Open **Education → Course knowledge**. The page should load without an API error.

For a real phone test, keep the HTTPS tunnel running and configure Meta's callback as `https://YOUR_DOMAIN/api/v1/webhooks/whatsapp`. Complete the platform-policy eligibility review for the actual deployment before launch.

## 2. Create the test catalog and access data

Use unique test names so results are easy to identify.

1. Create one active Education Agent and keep its purpose set to **Education**.
2. Create two active courses, for example **CMA USA** (`CMA`) and **CPA USA** (`CPA`). Add aliases used by students.
3. Create one active batch under each course.
4. Create a student and add their WhatsApp number as a **verified** identity in the current workspace.
5. Create two active enrollments for the same student and agent: one CMA enrollment and one CPA enrollment.
6. Confirm their dates include today. Do not create overlapping enrollments for the same student, agent, and course.

Expected result: both enrollments are visible under **Education → Enrollments**. No CRM lead is created.

## 3. Configure curriculum and paper permission

In **Education → Course knowledge**:

1. Select the Education Agent and CMA course.
2. Expand **Configure curricula, papers, batches, and enrollment access**.
3. Create a curriculum version and at least one paper, then bind the CMA batch to that curriculum.
4. Select the CMA enrollment, tick its authorized papers, and choose **Save authorized papers**.
5. Repeat with a separate curriculum and paper for CPA.

Expected result: each enrollment references an explicit curriculum and only its allowed paper IDs. Switching courses must not carry the selected paper across enrollments.

## 4. Upload, review, and publish isolated material

Repeat this workflow separately for CMA and CPA:

1. Select Agent, Course, Curriculum, Paper, and optional Batch.
2. Upload a small source containing a unique marker, such as `CMA_ONLY_MARKER` or `CPA_ONLY_MARKER`.
3. Wait for processing, then prepare an immutable snapshot.
4. Open the source version, compare extracted blocks with the original, and select the intended blocks.
5. Save the mapping, enter a review reason, approve the exact revision, and prepare its index.
6. Select the approved assignment, build a release candidate, inspect its manifest, and publish it.
7. Use **Preview as an enrolled student** to query each enrollment.

Expected result: CMA preview can retrieve `CMA_ONLY_MARKER` but never `CPA_ONLY_MARKER`, and vice versa. Overview mode must not search all papers. Processed but unpublished or withdrawn material must return no evidence.

## 5. Test the WhatsApp student journey

Send each message only after the previous reply arrives.

1. Send `Hi` from the verified student number.
   Expected: a stable numbered menu containing CMA and CPA.
2. Send `1`.
   Expected: the corresponding course is selected and a paper menu appears when needed.
3. Select a paper and ask a question containing the course's unique marker topic.
   Expected: the answer uses only that course's published evidence and citations.
4. Ask `Explain this more simply.`
   Expected: the same course/paper conversation continues.
5. Send `switch to CPA` (or the other configured course alias).
   Expected: the bot switches course and requests a CPA paper when needed.
6. Switch back to CMA and ask a follow-up.
   Expected: CMA history resumes without CPA history being injected.
7. Ask for an unenrolled third course such as `Send me ACCA notes`.
   Expected: access is denied and public fallback does not provide private ACCA tutoring.
8. While a course menu is open, send an invalid number such as `99`.
   Expected: the menu is refreshed; no accidental selection occurs.
9. Ask a real question before selecting a course, then choose course and paper.
   Expected: the original question is preserved and answered after selection.

## 6. Verify operations in the frontend

Return to **Education → Course knowledge** and select the agent:

- **Teacher review queue** shows low-confidence/no-evidence answers, their course/paper, evidence counts, and separate teacher-resolution fields.
- **Learning progress** shows per-enrollment and per-paper activity. It must not claim exam readiness.
- **Tutor context diagnostics** shows the selected enrollment, interaction state, revision, menu expiry, and any pending question.
- Use **Reset remembered selection**, then send another WhatsApp message. The bot should ask for course selection again without revoking enrollment access.

## 7. Revocation and race checks

1. Open a course menu, then suspend or expire the target enrollment before replying with its number.
   Expected: the old option is rejected and a current menu or access-help response is sent.
2. Withdraw a published source or assignment, then ask the same question again.
   Expected: withdrawn evidence is not used.
3. Revoke paper access after an answer is prepared but before delivery, where practical in staging.
   Expected: last-moment authorization blocks the stale reply.
4. Deliver the same inbound webhook event twice.
   Expected: one durable logical response; no duplicate practice/progress update.

Record the message IDs, timestamps, selected enrollment, response context fingerprint, and any academic review ID for failed cases. Do not use production student data for this test.
