"""Real-fixture regression for first-use course and paper menu numbers."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_education_runtime_authorization import _create_batch, _create_course, _create_enrollment

from northstar_api.database import SessionFactory
from northstar_api.models import Agent

pytestmark = pytest.mark.usefixtures("crm_test_plan")
pytest_plugins = ("test_course_knowledge_api",)


async def test_first_course_menu_numeric_reply_survives_without_prior_selection(client, course_setup):
    from northstar_api.course_knowledge_models import CourseStudySelection
    from northstar_api.education_student_identities import StudentIdentityType
    from northstar_api.services.course_study_access import authorize_study_access
    from northstar_api.services.education_runtime_authorization import EducationIdentityCandidate

    s = course_setup
    other = await _create_course(client, s["headers"], "ZZ-" + uuid4().hex[:8])
    other_batch = await _create_batch(
        client, s["headers"], course_id=other["id"], code="ZZ-B-" + uuid4().hex[:8]
    )
    await _create_enrollment(
        client,
        s["headers"],
        student_id=s["student"]["id"],
        course_id=other["id"],
        batch_id=other_batch["id"],
        agent_id=s["agent"]["id"],
    )
    async with SessionFactory() as session:
        agent = await session.get(Agent, UUID(s["agent"]["id"]))
        identity = EducationIdentityCandidate(StudentIdentityType.WHATSAPP, s["phone"])
        kwargs = dict(
            tenant_id=agent.tenant_id, workspace_id=agent.workspace_id, agent=agent, identity=identity
        )
        original_question = "Explain revenue recognition"
        decision, prompt = await authorize_study_access(session, **kwargs, message=original_question)
        assert not decision.authorized and "Choose an active course" in prompt
        await session.commit()
        state = await session.scalar(
            select(CourseStudySelection).where(CourseStudySelection.agent_id == agent.id)
        )
        assert state.enrollment_id is None and state.menu_open
        assert state.pending_question == original_question
        decision, prompt = await authorize_study_access(session, **kwargs, message="99")
        assert not decision.authorized and "Choose an active course" in prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="1")
        assert decision.authorized and decision.enrollment_id == UUID(s["enrollment"]["id"])
        assert "Choose a paper" in prompt
        await session.commit()
        decision, prompt = await authorize_study_access(session, **kwargs, message="1")
        assert decision.authorized and prompt is None
        await session.commit()
        await session.refresh(state)
        assert state.interaction_state == "ready_for_question"
        assert state.pending_question == original_question
