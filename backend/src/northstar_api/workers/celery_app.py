from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]
from kombu import Exchange, Queue  # type: ignore[import-untyped]

from northstar_api.config import get_settings

settings = get_settings()
jobs_exchange = Exchange("app.jobs.v1", type="direct", durable=True)
dead_letter_exchange = Exchange("app.jobs.dlx", type="direct", durable=True)

celery_app = Celery(
    "northstar",
    broker=settings.rabbitmq_url,
    include=[
        "northstar_api.workers.tasks",
        "northstar_api.workers.course_knowledge_tasks",
        "northstar_api.workers.telegram_tasks",
        "northstar_api.workers.instagram_tasks",
        "northstar_api.workers.facebook_messenger_tasks",
        "northstar_api.workers.slack_tasks",
        "northstar_api.modules.branding.workers.domain_tasks",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=1440,
    task_time_limit=1500,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"confirm_publish": True, "max_retries": 5},
    task_default_exchange=jobs_exchange.name,
    task_default_exchange_type="direct",
    task_default_routing_key="ingest.source",
    task_queues=(
        Queue(
            "ingest.source",
            exchange=jobs_exchange,
            routing_key="ingest.source",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "ingest.failed",
            },
        ),
        Queue("ingest.failed", exchange=dead_letter_exchange, routing_key="ingest.failed", durable=True),
        Queue("operations", exchange=jobs_exchange, routing_key="operations", durable=True),
        Queue(
            "whatsapp.inbound",
            exchange=jobs_exchange,
            routing_key="whatsapp.inbound",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "whatsapp.failed",
            },
        ),
        Queue(
            "whatsapp.outbound",
            exchange=jobs_exchange,
            routing_key="whatsapp.outbound",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "whatsapp.failed",
            },
        ),
        Queue(
            "whatsapp.failed",
            exchange=dead_letter_exchange,
            routing_key="whatsapp.failed",
            durable=True,
        ),
        Queue(
            "telegram.outbound",
            exchange=jobs_exchange,
            routing_key="telegram.outbound",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "telegram.failed",
            },
        ),
        Queue(
            "telegram.failed",
            exchange=dead_letter_exchange,
            routing_key="telegram.failed",
            durable=True,
        ),
        Queue(
            "instagram.outbound",
            exchange=jobs_exchange,
            routing_key="instagram.outbound",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "instagram.failed",
            },
        ),
        Queue(
            "instagram.failed",
            exchange=dead_letter_exchange,
            routing_key="instagram.failed",
            durable=True,
        ),
        Queue(
            "facebook_messenger.outbound",
            exchange=jobs_exchange,
            routing_key="facebook_messenger.outbound",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "facebook_messenger.failed",
            },
        ),
        Queue(
            "facebook_messenger.failed",
            exchange=dead_letter_exchange,
            routing_key="facebook_messenger.failed",
            durable=True,
        ),
        Queue(
            "slack.outbound",
            exchange=jobs_exchange,
            routing_key="slack.outbound",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": dead_letter_exchange.name,
                "x-dead-letter-routing-key": "slack.failed",
            },
        ),
        Queue(
            "slack.failed",
            exchange=dead_letter_exchange,
            routing_key="slack.failed",
            durable=True,
        ),
    ),
    task_routes={
        "northstar.ingest_source": {"queue": "ingest.source", "routing_key": "ingest.source"},
        "northstar.prepare_course_assignment": {"queue": "ingest.source", "routing_key": "ingest.source"},
        "northstar.process_whatsapp_inbound": {
            "queue": "whatsapp.inbound",
            "routing_key": "whatsapp.inbound",
        },
        "northstar.send_whatsapp_human_reply": {
            "queue": "whatsapp.outbound",
            "routing_key": "whatsapp.outbound",
        },
        "northstar.send_telegram_message": {
            "queue": "telegram.outbound",
            "routing_key": "telegram.outbound",
        },
        "northstar.send_instagram_message": {
            "queue": "instagram.outbound",
            "routing_key": "instagram.outbound",
        },
        "northstar.send_facebook_messenger_message": {
            "queue": "facebook_messenger.outbound",
            "routing_key": "facebook_messenger.outbound",
        },
        "northstar.send_slack_message": {
            "queue": "slack.outbound",
            "routing_key": "slack.outbound",
        },
        "northstar.verify_workspace_brand_domain": {
            "queue": "operations",
            "routing_key": "operations",
        },
        "northstar.check_workspace_brand_tls": {
            "queue": "operations",
            "routing_key": "operations",
        },
    },
)


def main() -> None:
    celery_app.worker_main(["worker", "--loglevel=INFO"])
