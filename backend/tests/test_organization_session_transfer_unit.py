from uuid import uuid4

import pytest

from northstar_api.services.organization_session_transfer import (
    OrganizationSessionError,
    TRANSFER_REFRESH_FAMILY,
    access_identity,
    refresh_identity,
    transfer_arguments,
    transfer_family,
)


def claims():
    return {"type": "access", "sub": str(uuid4()), "tid": str(uuid4()), "jti": "access-1", "cv": 3}


def test_verified_access_and_refresh_proof_must_match():
    access = claims()
    identity = access_identity(access)
    refresh = {**access, "type": "refresh", "fid": "family-1", "jti": "refresh-1"}
    assert refresh_identity(refresh, identity) == ("family-1", "refresh-1")
    assert identity.credential_version == 3


@pytest.mark.parametrize("patch", [{"sub": None}, {"tid": "not-a-uuid"}, {"cv": True}, {"cv": -1},
                                   {"cv": "3"}, {"type": "widget"}, {"jti": "colon:key"}])
def test_invalid_verified_claim_shapes_fail_closed(patch):
    with pytest.raises(OrganizationSessionError):
        access_identity({**claims(), **patch})


@pytest.mark.parametrize("field,value", [("sub", str(uuid4())), ("tid", str(uuid4())), ("cv", 4),
                                         ("type", "access"), ("fid", "unsafe:key"), ("cv", True)])
def test_foreign_or_stale_refresh_proof_is_rejected(field, value):
    access = claims()
    identity = access_identity(access)
    refresh = {**access, "type": "refresh", "fid": "family-1", "jti": "refresh-1", field: value}
    with pytest.raises(OrganizationSessionError):
        refresh_identity(refresh, identity)


def test_legacy_credential_version_zero_is_explicitly_supported():
    value = claims()
    del value["cv"]
    identity = access_identity(value)
    refresh = {**value, "type": "refresh", "fid": "family-1"}
    assert refresh_identity(refresh, identity) == ("family-1", "access-1")


@pytest.mark.parametrize("old,new,ttl", [("same", "same", 30), ("old", "new", 0),
                                        ("old", "new", True), ("bad:key", "new", 30)])
def test_invalid_family_transfer_input_is_rejected(old, new, ttl):
    with pytest.raises(OrganizationSessionError):
        transfer_arguments(old, "old-jti", new, "new-jti", ttl, "access-jti")


@pytest.mark.asyncio
async def test_transfer_uses_atomic_compare_and_new_family_and_revocation_key():
    class Store:
        async def eval(self, *args):
            self.args = args
            return 1
    store = Store()
    assert await transfer_family(store, old_family="old", old_token="old-jti", new_family="new",
                                 new_token="new-jti", ttl_seconds=90, access_token_id="access-jti")
    assert store.args == (TRANSFER_REFRESH_FAMILY, 3, "northstar:refresh-family:old", "northstar:refresh-family:new",
                          "northstar:revoked:access-jti", "old-jti", "new-jti", 90)


@pytest.mark.asyncio
async def test_losing_transfer_does_not_report_success():
    class Store:
        async def eval(self, *args):
            return 0
    assert not await transfer_family(Store(), old_family="old", old_token="old-jti", new_family="new",
                                     new_token="new-jti", ttl_seconds=90, access_token_id="access-jti")


@pytest.mark.asyncio
async def test_failed_selection_cleanup_is_compare_and_delete_not_unconditional_delete():
    from northstar_api.services.organization_session_transfer import REVOKE_UNDELIVERED_FAMILY, revoke_undelivered_family
    class Store:
        async def eval(self, *args):
            self.args = args
            return 0
    store = Store()
    await revoke_undelivered_family(store, "new-family", "new-jti")
    assert store.args == (REVOKE_UNDELIVERED_FAMILY, 1, "northstar:refresh-family:new-family", "new-jti")
