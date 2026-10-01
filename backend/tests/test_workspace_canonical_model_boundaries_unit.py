"""Section 23: canonical model paths must not fork the existing database models."""

import pytest
from sqlalchemy import inspect as sqlalchemy_inspect

from northstar_api.database import Base
from northstar_api.models import (
    Workspace,
    WorkspaceMemberAgentAccess,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceStatus,
)
from northstar_api.modules.workspace import models as feature_models
from northstar_api.modules.workspace.contracts import CustomRole, RolesSettings, TeamsSettings, WorkspaceTeam
from northstar_api.modules.workspace.conversation_assignment_model import WorkspaceConversationAssignment
from northstar_api.workspace_invitations import (
    WorkspaceInvitation,
    WorkspaceInvitationAgentAccess,
    WorkspaceInvitationStatus,
)


def test_canonical_model_exports_keep_exact_existing_class_objects() -> None:
    expected = {
        "Workspace": Workspace,
        "WorkspaceStatus": WorkspaceStatus,
        "WorkspaceMembership": WorkspaceMembership,
        "WorkspaceMemberAgentAccess": WorkspaceMemberAgentAccess,
        "WorkspaceRole": WorkspaceRole,
        "CustomRole": CustomRole,
        "RolesSettings": RolesSettings,
        "WorkspaceTeam": WorkspaceTeam,
        "TeamsSettings": TeamsSettings,
        "WorkspaceInvitation": WorkspaceInvitation,
        "WorkspaceInvitationAgentAccess": WorkspaceInvitationAgentAccess,
        "WorkspaceInvitationStatus": WorkspaceInvitationStatus,
        "WorkspaceConversationAssignment": WorkspaceConversationAssignment,
    }
    existing_tables = dict(Base.metadata.tables)
    for name, original in expected.items():
        assert getattr(feature_models, name) is original, name
        assert name in feature_models.__all__
    assert dict(Base.metadata.tables) == existing_tables
    assert sqlalchemy_inspect(feature_models.Workspace) is sqlalchemy_inspect(Workspace)
    assert sqlalchemy_inspect(feature_models.WorkspaceMembership) is sqlalchemy_inspect(WorkspaceMembership)
    assert sqlalchemy_inspect(feature_models.WorkspaceInvitation) is sqlalchemy_inspect(WorkspaceInvitation)
    assert not hasattr(feature_models.WorkspaceTeam, "__table__")
    assert not hasattr(feature_models.CustomRole, "__table__")


def test_unknown_model_export_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        getattr(feature_models, "NotAnExistingWorkspaceModel")
