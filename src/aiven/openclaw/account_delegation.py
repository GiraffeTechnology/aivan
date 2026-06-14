from __future__ import annotations
import os
from aiven.openclaw.contracts import OpenClawManagedAccount, ALLOWED_PERMISSIONS, FORBIDDEN_ACTIONS
from aiven.utils.time_utils import utcnow_iso

def register_account(db_session, data: dict) -> OpenClawManagedAccount:
    """Register an OpenClaw-managed account. AIVEN never stores passwords or sessions."""
    account_connection_id = data.get("account_connection_id", "")
    if not account_connection_id:
        from aiven.utils.ids import new_account_id
        account_connection_id = new_account_id()

    requested_permissions = data.get("permissions", [])
    safe_permissions = [p for p in requested_permissions if p in ALLOWED_PERMISSIONS]
    forbidden_found = [p for p in requested_permissions if p in FORBIDDEN_ACTIONS]
    if forbidden_found:
        raise ValueError(f"Forbidden permissions requested: {forbidden_found}. AIVEN does not support these actions.")

    account = OpenClawManagedAccount(
        account_connection_id=account_connection_id,
        platform=data.get("platform", ""),
        channel=data.get("channel", ""),
        channel_account_id=data.get("channel_account_id", ""),
        owner_user_id=data.get("owner_user_id"),
        display_name=data.get("display_name"),
        status=data.get("status", "connected"),
        permissions=safe_permissions,
        allowed_actions=data.get("allowed_actions", []),
        expires_at=data.get("expires_at"),
        created_at=utcnow_iso(),
        updated_at=utcnow_iso(),
        metadata=data.get("metadata", {}),
    )

    from aiven.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db_session)
    repo.upsert(account_connection_id, {
        "platform": account.platform,
        "channel": account.channel,
        "channel_account_id": account.channel_account_id,
        "owner_user_id": account.owner_user_id or "",
        "display_name": account.display_name or "",
        "status": account.status,
        "permissions_json": account.permissions,
        "allowed_actions_json": account.allowed_actions,
        "expires_at": account.expires_at or "",
        "metadata_json": account.metadata,
    })

    _log_account_event(db_session, account_connection_id, "ACCOUNT_REGISTERED", account.platform)
    return account

def revoke_account(db_session, account_connection_id: str) -> bool:
    from aiven.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db_session)
    result = repo.revoke(account_connection_id)
    if result:
        _log_account_event(db_session, account_connection_id, "ACCOUNT_REVOKED", "")
    return result is not None

def check_permission(db_session, account_connection_id: str, permission: str) -> bool:
    if permission in FORBIDDEN_ACTIONS:
        return False
    from aiven.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db_session)
    account = repo.get(account_connection_id)
    if not account:
        return False
    if account.status == "revoked":
        return False
    _log_account_event(db_session, account_connection_id, "ACCOUNT_PERMISSION_CHECKED", permission)
    return permission in (account.permissions_json or [])

def list_accounts(db_session) -> list[OpenClawManagedAccount]:
    from aiven.db.repositories.account_repo import AccountRepository
    repo = AccountRepository(db_session)
    records = repo.list_active()
    return [
        OpenClawManagedAccount(
            account_connection_id=r.account_connection_id,
            platform=r.platform,
            channel=r.channel or "",
            channel_account_id=r.channel_account_id or "",
            owner_user_id=r.owner_user_id or None,
            display_name=r.display_name or None,
            status=r.status,
            permissions=r.permissions_json or [],
            allowed_actions=r.allowed_actions_json or [],
            expires_at=r.expires_at or None,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
            metadata=r.metadata_json or {},
        )
        for r in records
    ]

def _log_account_event(db_session, account_connection_id: str, event_type: str, detail: str):
    try:
        from aiven.db.repositories.event_repo import ExecutionEventRepository
        repo = ExecutionEventRepository(db_session)
        repo.append(
            project_id="system",
            event_type=event_type,
            summary=f"{event_type}: {account_connection_id} ({detail})",
            payload={"account_connection_id": account_connection_id, "detail": detail},
            actor="account_delegation",
        )
    except Exception:
        pass
