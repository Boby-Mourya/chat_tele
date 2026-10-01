from northstar_api.modules.branding.models import (
    WorkspaceBrand,
    WorkspaceBrandAsset,
    WorkspaceBrandSurface,
    WorkspaceBrandTheme,
    WorkspaceBrandVersion,
    WorkspaceCustomDomain,
    WorkspaceDashboardLayout,
    WorkspaceEmailBrand,
    WorkspaceWidgetBrand,
)


def test_normalized_workspace_brand_tables_are_tenant_and_workspace_scoped() -> None:
    models = [
        WorkspaceBrand,
        WorkspaceBrandAsset,
        WorkspaceBrandSurface,
        WorkspaceBrandTheme,
        WorkspaceBrandVersion,
        WorkspaceCustomDomain,
        WorkspaceDashboardLayout,
        WorkspaceEmailBrand,
        WorkspaceWidgetBrand,
    ]
    for model in models:
        columns = set(model.__table__.columns.keys())
        assert "tenant_id" in columns, model.__tablename__
        assert "workspace_id" in columns, model.__tablename__


def test_branding_tables_are_separated_by_responsibility() -> None:
    assert WorkspaceBrand.__tablename__ == "workspace_brand"
    assert WorkspaceBrandAsset.__tablename__ == "workspace_brand_asset"
    assert WorkspaceBrandTheme.__tablename__ == "workspace_brand_theme"
    assert WorkspaceBrandSurface.__tablename__ == "workspace_brand_surface"
    assert WorkspaceBrandVersion.__tablename__ == "workspace_brand_version"
    assert WorkspaceCustomDomain.__tablename__ == "workspace_custom_domain"
    assert WorkspaceDashboardLayout.__tablename__ == "workspace_dashboard_layout"
    assert WorkspaceEmailBrand.__tablename__ == "workspace_email_brand"
    assert WorkspaceWidgetBrand.__tablename__ == "workspace_widget_brand"
