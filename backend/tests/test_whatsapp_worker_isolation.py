from pathlib import Path

import pytest

from northstar_api.services.chat import FAILED_RESPONSE_PLACEHOLDER
from northstar_api.workers.celery_app import celery_app
from northstar_api.workers.tasks import (
    deliverable_whatsapp_answer,
    ingest_source,
    process_whatsapp_inbound,
    send_whatsapp_human_reply,
)


def test_task_deadlines_do_not_reach_the_broker_acknowledgement_timeout():
    broker_acknowledgement_timeout = 30 * 60
    for task in (ingest_source, process_whatsapp_inbound, send_whatsapp_human_reply):
        soft = task.soft_time_limit or celery_app.conf.task_soft_time_limit
        hard = task.time_limit or celery_app.conf.task_time_limit
        assert 0 < soft < hard < broker_acknowledgement_timeout
    ingestion_limit = ingest_source.time_limit or celery_app.conf.task_time_limit
    assert process_whatsapp_inbound.time_limit < ingestion_limit
    assert send_whatsapp_human_reply.time_limit < ingestion_limit


def test_compose_routes_whatsapp_to_a_worker_without_ingestion():
    # Queue subscriptions are a deployment contract: declaring task_routes alone
    # still lets an unrestricted worker consume every queue.
    compose = (Path(__file__).resolve().parents[2] / 'compose.yaml').read_text()
    general = compose.split('  worker: &celery-worker\n', 1)[1].split('  whatsapp-worker:', 1)[0]
    whatsapp = compose.split('  whatsapp-worker:\n', 1)[1].split('  job-dispatcher:', 1)[0]
    assert '--queues=whatsapp.inbound,whatsapp.outbound' in whatsapp
    assert '--queues=ingest.source,operations,' in general
    assert 'whatsapp.inbound' not in general
    assert 'ingest.source' not in whatsapp
    assert '<<: *celery-worker' in whatsapp


def test_whatsapp_task_routes_match_the_dedicated_queue_subscriptions():
    assert celery_app.conf.task_routes[process_whatsapp_inbound.name]['queue'] == 'whatsapp.inbound'
    assert celery_app.conf.task_routes[send_whatsapp_human_reply.name]['queue'] == 'whatsapp.outbound'
    assert celery_app.conf.worker_prefetch_multiplier == 1


@pytest.mark.parametrize("answer", ["", "   ", FAILED_RESPONSE_PLACEHOLDER])
def test_whatsapp_never_delivers_failed_assistant_placeholders(answer: str) -> None:
    with pytest.raises(RuntimeError, match="incomplete assistant response"):
        deliverable_whatsapp_answer(answer)


def test_whatsapp_delivers_completed_answers() -> None:
    assert deliverable_whatsapp_answer("A grounded answer") == "A grounded answer"
