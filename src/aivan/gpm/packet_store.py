"""GPMPacketStore — write-through cache backed by giraffe-db.

Behaviour:
- save(): write giraffe-db first, then memory; on DB failure memory-only + warning
- get(): memory hit (tenant-filtered) -> return; miss -> fetch giraffe-db -> backfill memory
- update_status(): write giraffe-db + sync memory; on DB failure memory-only
- write_audit(): giraffe-db only (no cache); failure -> False, no raise
- list_by_tenant(): giraffe-db preferred; on failure memory fallback (tenant-filtered)

Tenant isolation applies in all paths: in-memory fallback never leaks
another tenant's packets.
"""
from __future__ import annotations

import logging
from typing import Optional

from aivan.gpm.giraffe_db_client import GiraffeDBClient, GiraffeDBClientError

logger = logging.getLogger(__name__)


class GPMPacketStore:
    def __init__(self, db_client: Optional[GiraffeDBClient] = None) -> None:
        self._mem: dict[str, dict] = {}
        self._db = db_client
        self._durable = False

        if self._db is not None:
            try:
                self._db.check_schema_version()
                self._durable = True
                logger.info("GPMPacketStore: giraffe-db available — durable mode")
            except Exception as exc:
                logger.warning(
                    "GPMPacketStore: giraffe-db unavailable (%s) — "
                    "in-memory fallback. Packets will NOT survive restart.",
                    exc,
                )
        else:
            logger.warning(
                "GPMPacketStore: no db_client — in-memory only. "
                "Set GIRAFFE_DB_BASE_URL to enable persistence."
            )

    # ── public API ─────────────────────────────────────────────────────────

    def save(self, packet: dict) -> dict:
        pid = packet["packet_id"]
        if self._durable:
            try:
                saved = self._db.create_packet(packet)
                self._mem[pid] = saved
                return saved
            except GiraffeDBClientError as exc:
                logger.warning(
                    "GPMPacketStore.save: giraffe-db write failed (%s) — memory only", exc
                )
        self._mem[pid] = packet
        return packet

    def get(self, packet_id: str, tenant_id: str | None = None) -> Optional[dict]:
        cached = self._mem.get(packet_id)
        if cached is not None:
            # Enforce tenant isolation in memory — never return another tenant's packet.
            if tenant_id is not None and cached.get("tenant_id") != tenant_id:
                return None
            return cached
        if self._durable:
            try:
                row = self._db.get_packet(packet_id, tenant_id=tenant_id)
                if row:
                    self._mem[packet_id] = row
                return row
            except GiraffeDBClientError as exc:
                logger.warning("GPMPacketStore.get: giraffe-db read failed (%s)", exc)
        return None

    def update_status(
        self,
        packet_id: str,
        approval_status: str,
        operator_id: str,
        notes: Optional[str] = None,
        tenant_id: str | None = None,
    ) -> Optional[dict]:
        if self._durable:
            try:
                updated = self._db.update_packet_status(
                    packet_id, approval_status, operator_id, notes, tenant_id=tenant_id
                )
                self._mem[packet_id] = updated
                return updated
            except GiraffeDBClientError as exc:
                logger.warning(
                    "GPMPacketStore.update_status: giraffe-db failed (%s) — memory only", exc
                )

        if packet_id in self._mem:
            packet = self._mem[packet_id]
            if tenant_id is not None and packet.get("tenant_id") != tenant_id:
                return None
            self._mem[packet_id].update({
                "approval_status": approval_status,
                "operator_id": operator_id,
                **(({"notes": notes}) if notes else {}),
            })
            return self._mem[packet_id]
        return None

    def write_audit(
        self,
        packet_id: str,
        operator_id: str,
        action: str,
        notes: Optional[str] = None,
        tenant_id: str = "default",
    ) -> bool:
        """Write audit record to giraffe-db only. Returns False on failure without raising."""
        if self._durable:
            try:
                self._db.create_audit_record(packet_id, operator_id, action, notes, tenant_id)
                return True
            except GiraffeDBClientError as exc:
                logger.warning("GPMPacketStore.write_audit: failed (%s)", exc)
        return False

    def list_by_tenant(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
    ) -> list[dict]:
        if self._durable:
            try:
                return self._db.list_packets(tenant_id=tenant_id, status=status)
            except GiraffeDBClientError as exc:
                logger.warning(
                    "GPMPacketStore.list_by_tenant: giraffe-db failed (%s) — memory fallback", exc
                )
        return [
            p for p in self._mem.values()
            if p.get("tenant_id") == tenant_id
            and (status is None or p.get("approval_status") == status)
        ]

    @property
    def is_durable(self) -> bool:
        return self._durable
