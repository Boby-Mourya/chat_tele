"""Approved starter-template contracts; never accepts a caller-provided recipe."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from northstar_api.onboarding_contract import STARTER_CATALOG, SetupContract, granted_starter_content


class TemplateCloneRequest(SetupContract):
    idempotency_key: UUID
    catalog_version: int = Field(ge=1, strict=True)
    name: str = Field(min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def visible_name(cls, value: str) -> str:
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError("Agent names cannot contain control or invisible formatting characters")
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Enter an agent name containing at least two visible characters")
        return normalized


class TemplateCloneOut(SetupContract):
    request_id: UUID
    catalog_id: str
    catalog_version: int
    agent_id: UUID
    workspace_id: UUID
    name: str
    purpose: Literal["support"] = "support"
    initial_status: Literal["draft"] = "draft"
    sample: Literal[True] = True
    created_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class StarterTemplate:
    id: str
    version: int
    instructions: str
    title: str

    @property
    def digest(self) -> str:
        value = [self.id, self.version, self.instructions, "support", "draft", "website"]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


# Only this existing approved catalog item has an executable clone recipe.
# Tutorials remain read-only. Future recipes must receive an explicit version
# and corresponding purpose/permission tests before entering this registry.
TEMPLATE_IDS = frozenset({"support-template"})


def catalog_for(grants: list[str]) -> list[dict[str, str | int | bool]]:
    return [
        {**item, "cloneable": item["id"] in TEMPLATE_IDS and item["kind"] == "template"}
        for item in granted_starter_content(grants)
    ]


def approved_template(catalog_id: str, version: int, grants: list[str]) -> StarterTemplate:
    if catalog_id not in set(grants) or catalog_id not in TEMPLATE_IDS:
        raise LookupError("This starter template is not available to this organization")
    for item in STARTER_CATALOG:
        if item["id"] == catalog_id and item["kind"] == "template":
            if item["version"] != version:
                raise ValueError("The starter catalog changed. Reload it before creating a copy")
            return StarterTemplate(catalog_id, version, str(item["content"]), str(item["title"]))
    raise LookupError("This starter template has been withdrawn")


def clone_fingerprint(template: StarterTemplate, request: TemplateCloneRequest) -> str:
    payload = [template.id, template.version, template.digest, request.name]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
