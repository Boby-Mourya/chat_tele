"""Typed onboarding contracts, independent of persistence and provider services."""
from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from pydantic.alias_generators import to_camel


class SetupContract(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class OrganizationProfileDraft(SetupContract):
    organization_type: Literal["institution", "business"] = "institution"
    display_name: str = Field(default="", max_length=160)
    organization_subtype: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=120)
    timezone: str = "Asia/Kolkata"
    preferred_language: str = Field(default="English", min_length=2, max_length=60)
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] = "DD/MM/YYYY"
    contact_name: str = Field(default="", max_length=160)
    contact_email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=40)
    website: HttpUrl | None = None
    description: str = Field(default="", max_length=2000)
    teaching_focus: str = Field(default="", max_length=1000)
    program_categories: list[str] = Field(default_factory=list, max_length=20)
    learner_volume_band: str = Field(default="", max_length=60)
    team_size_band: str = Field(default="", max_length=60)
    use_cases: list[Literal["education", "support", "lead_generation"]] = Field(default_factory=list, max_length=3)
    workspace_name: str = Field(default="", max_length=160)
    workspace_slug: str = Field(default="default", min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value

    @field_validator("contact_email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized:
            from email_validator import EmailNotValidError, validate_email
            try:
                normalized = str(validate_email(normalized, check_deliverability=False).normalized)
            except EmailNotValidError as exc:
                raise ValueError("Enter a valid contact email") from exc
        return normalized

    @field_validator("program_categories")
    @classmethod
    def normalized_programs(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip() for item in values if item.strip()))
        if any(len(item) > 120 for item in normalized):
            raise ValueError("Program names must not exceed 120 characters")
        return normalized

    def missing_fields(self) -> list[str]:
        required = ["display_name", "organization_subtype", "category", "country", "contact_name", "contact_email", "workspace_name"]
        if self.organization_type == "institution":
            required += ["teaching_focus", "program_categories", "learner_volume_band"]
        else:
            required += ["description", "team_size_band", "use_cases"]
        return [to_camel(name) for name in required if not (value := getattr(self, name)) or (isinstance(value, str) and not value.strip())]


class ProfileSave(SetupContract):
    expected_revision: int = Field(ge=0)
    profile: OrganizationProfileDraft
    complete: bool = False

    @model_validator(mode="after")
    def completed_profile_is_valid(self) -> ProfileSave:
        missing = self.profile.missing_fields()
        if self.complete and missing:
            raise ValueError("Complete the required fields: " + ", ".join(missing))
        return self


class BrandingChoiceSave(SetupContract):
    expected_revision: int = Field(ge=0)
    choice: Literal["customize", "keep_default", "deferred"]


CATALOG_VERSION = 1
STARTER_CATALOG: tuple[dict[str, str | int | bool], ...] = (
    {"id": "getting-started", "version": 1, "title": "Start your first workspace", "kind": "tutorial", "sample": True,
     "content": "Create a draft agent, select its purpose, add approved knowledge, and test its answers before deployment. Invite staff with the least access their work requires. These instructions are free starter material, not your private workspace knowledge."},
    {"id": "support-template", "version": 1, "title": "Support assistant instruction template", "kind": "template", "sample": True,
     "content": "Answer using approved support knowledge. Cite the relevant source. When evidence is missing, say so and offer human escalation. Do not invent prices, policies or account details. Never request passwords or secret keys. Configure this template in a draft agent and test it with your own approved sources."},
    {"id": "education-boundaries", "version": 1, "title": "Education access checklist", "kind": "tutorial", "sample": True,
     "content": "Keep students separate from staff accounts. Verify the student's course and enrollment before retrieving private learning material. Test with both authorized and unauthorized students. Education conversations must never create leads or invoke CRM. This starter tutorial does not enroll a student in a course."},
)


def granted_starter_content(grants: list[str]) -> list[dict[str, str | int | bool]]:
    allowed = set(grants)
    return [dict(item) for item in STARTER_CATALOG if item["id"] in allowed]
