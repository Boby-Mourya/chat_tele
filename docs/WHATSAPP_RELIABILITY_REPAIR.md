# WhatsApp processing repair

Date: 2026-09-15

## Cause

The connected number and published bot were valid. Incoming webhooks reached
the database, but RabbitMQ had no consumers for the WhatsApp queues.

The shared Celery worker logged `PRECONDITION_FAILED` after an ingestion job
remained unacknowledged for 1,800,000 milliseconds. Its parent process remained
running during shutdown, so Docker's restart-on-exit policy did not recover it.
WhatsApp messages then stayed queued or reported `queue dispatch unavailable`.

RabbitMQ closes a consumer channel when acknowledgements exceed its deadline;
Celery task time limits prevent a job from occupying a process indefinitely.
See [RabbitMQ acknowledgement timeouts](https://www.rabbitmq.com/docs/consumers#acknowledgement-timeout)
and [Celery task time limits](https://docs.celeryq.dev/en/stable/userguide/workers.html#time-limits).

## Changes deployed

- Added `whatsapp-worker` to Docker Compose. It consumes only
  `whatsapp.inbound` and `whatsapp.outbound`.
- Gave the general worker explicit subscriptions excluding WhatsApp and
  dead-letter queues. Document ingestion no longer shares WhatsApp's consumer
  channel or process pool.
- Set default Celery soft/hard task limits to 24/25 minutes, below RabbitMQ's
  default 30-minute acknowledgement deadline.
- Set WhatsApp task soft/hard limits to 4/5 minutes.
- Limited each OCR SDK request to 90 seconds with SDK retries disabled. The
  existing Celery retry policy owns ingestion retries.
- Updated the older signup tests to enter Facebook signup through the current
  account-manager screen and provide the current account/activity API mocks.

The current frontend design, account credentials, number assignment, and
existing conversation data remain intact.

## Verified

- 50 backend WhatsApp, ingestion and isolation tests passed.
- 60 frontend WhatsApp, deployment and integration tests passed.
- Python lint passed for the changed backend files.
- Docker Compose validates; API, web, general worker and WhatsApp worker are healthy.
- Runtime inspection confirms the dedicated worker's exact two subscriptions.
- Both WhatsApp queues have one consumer, zero ready messages and zero
  unacknowledged messages. There are no queued, processing or failed inbound
  WhatsApp records remaining at verification time.
- The previously queued incoming messages completed after recovery. Meta sent
  delivery receipts for the resulting replies, followed by a read receipt.
- The public ngrok web health endpoint returns HTTP 200.

The historical rejected/ignored inbound records were retained. They were not
manually replayed. No synthetic message was sent to a contact during testing.

## Running the repaired setup

Use `start.bat`; it now includes the dedicated WhatsApp worker. Its concurrency
defaults to 2 and can be set with `WHATSAPP_CELERY_CONCURRENCY`.
Keep Docker and ngrok running for incoming messages and replies.

Detailed test and deployment logs are in `reports/recovery/whatsapp-*.txt` and
`reports/recovery/whatsapp-*.log` (ignored local reports).
