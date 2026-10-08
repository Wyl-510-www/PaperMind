"""Trace Exporter: 导出服务内部 trace 供测试框架使用"""
from __future__ import annotations
import logging
from typing import Any, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class TraceExporter:
    def __init__(self, db_session_factory, index_adapter, writer=None):
        self.db_session_factory = db_session_factory
        self.index_adapter = index_adapter
        self.writer = writer

    def export_truth_snapshot(self, user_id: str, tenant_id: str = "default") -> Dict[str, Any]:
        try:
            from server.memory_v2.models import Claim
            from server.memory_v2.store.entity_store import EntityRecord
            
            mysql_claims = []
            mysql_entities = []
            qdrant_vectors = []
            
            with self.db_session_factory() as session:
                claims = session.query(Claim).filter(
                    Claim.tenant_id == tenant_id,
                    Claim.user_id == user_id
                ).all()
                
                mysql_claims = [{
                    "claim_id": c.claim_id,
                    "text": c.text,
                    "memory_type": c.memory_type,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "turn_id": c.turn_id
                } for c in claims]
                
                entities = session.query(EntityRecord).filter(
                    EntityRecord.tenant_id == tenant_id,
                    EntityRecord.user_id == user_id
                ).all()
                
                mysql_entities = [{
                    "entity_id": e.entity_id,
                    "entity_type": e.entity_type,
                    "name": e.name,
                    "created_at": e.created_at.isoformat() if e.created_at else None
                } for e in entities]
            
            try:
                from server.memory_v2.config import config
                index = self.index_adapter._index
                scroll_result = index.client.scroll(
                    collection_name=config.qdrant_collection_name,
                    scroll_filter={"must": [
                        {"key": "tenant_id", "match": {"value": tenant_id}},
                        {"key": "user_id", "match": {"value": user_id}}
                    ]},
                    limit=100,
                    with_payload=True,
                    with_vectors=False
                )
                points = scroll_result[0]
                qdrant_vectors = [{"point_id": str(p.id), "payload": p.payload} for p in points]
            except Exception as e:
                logger.warning(f"读取 Qdrant 失败: {e}")
                qdrant_vectors = [{"error": str(e)}]
            
            return {
                "mysql_claims": mysql_claims,
                "mysql_entities": mysql_entities,
                "qdrant_vectors": qdrant_vectors,
                "snapshot_time": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.exception(f"导出 truth_snapshot 失败")
            return {"error": str(e)}
