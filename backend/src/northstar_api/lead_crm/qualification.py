from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from northstar_api.lead_crm.channels import CanonicalInboundEvent
from northstar_api.lead_crm.qualification_models import LeadQualificationRule


@dataclass(frozen=True, slots=True)
class QualificationDecision:
    matched_rule_id: UUID | None
    create_lead: bool
    qualify: bool
    score: int
    reason: str
    sync_to_crm: bool


class LeadQualificationEngine:
    @staticmethod
    def _one_of(value: object, expected: object) -> bool:
        if isinstance(expected, list):
            return value in expected
        return value == expected

    def _matches(self, event: CanonicalInboundEvent, conditions: dict[str, Any]) -> bool:
        message_text = event.message.text if event.message else None
        checks: dict[str, object] = {
            "channel": event.provider.value,
            "provider": event.provider.value,
            "emailAvailable": bool(event.sender.email),
            "phoneAvailable": bool(event.sender.phone),
            "senderExternalIdAvailable": bool(event.sender.external_id),
        }
        for key, expected in conditions.items():
            if key in checks:
                if not self._one_of(checks[key], expected):
                    return False
                continue
            if key == "messageContains":
                if not message_text:
                    return False
                needles = expected if isinstance(expected, list) else [expected]
                lowered = message_text.casefold()
                if not any(str(needle).casefold() in lowered for needle in needles):
                    return False
                continue
            if key == "minimumMessageLength":
                try:
                    if len(message_text or "") < int(expected):
                        return False
                except (TypeError, ValueError):
                    return False
                continue
            if key == "campaign":
                campaign_name = event.campaign_attribution.get("name") or event.campaign_attribution.get(
                    "campaign"
                )
                if not self._one_of(campaign_name, expected):
                    return False
                continue
            if key == "metadataEquals":
                if not isinstance(expected, dict):
                    return False
                if any(event.metadata.get(str(field)) != value for field, value in expected.items()):
                    return False
                continue
            return False
        return True

    async def decide(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        event: CanonicalInboundEvent,
        fallback: dict[str, Any] | None = None,
    ) -> QualificationDecision:
        rules = list(
            await session.scalars(
                select(LeadQualificationRule)
                .where(
                    LeadQualificationRule.tenant_id == tenant_id,
                    LeadQualificationRule.enabled.is_(True),
                )
                .order_by(LeadQualificationRule.priority, LeadQualificationRule.created_at)
            )
        )
        for rule in rules:
            if not self._matches(event, rule.conditions_json or {}):
                continue
            actions = rule.actions_json or {}
            score = max(0, min(int(actions.get("score", 0)), 100))
            qualify = bool(actions.get("qualify", score > 0))
            return QualificationDecision(
                matched_rule_id=rule.id,
                create_lead=bool(actions.get("createLead", True)),
                qualify=qualify,
                score=score,
                reason=str(actions.get("reason") or f"Matched rule: {rule.name}")[:1000],
                sync_to_crm=bool(actions.get("syncToCRM", qualify)),
            )

        fallback = fallback or {}
        score = max(0, min(int(fallback.get("score", 0)), 100))
        qualify = bool(fallback.get("qualify", False))
        return QualificationDecision(
            matched_rule_id=None,
            create_lead=bool(fallback.get("createLead", False)),
            qualify=qualify,
            score=score,
            reason=str(fallback.get("reason") or "No qualification rule matched")[:1000],
            sync_to_crm=bool(fallback.get("syncToCRM", qualify)),
        )


lead_qualification_engine = LeadQualificationEngine()
