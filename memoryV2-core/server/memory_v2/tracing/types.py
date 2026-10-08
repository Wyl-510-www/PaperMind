"""Chain Trace 数据结构定义"""
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class WriteTrace:
    """W 层（写入）追踪信息"""
    extractor_candidate_ids: List[str] = field(default_factory=list)
    truth_aggregate_ids: List[str] = field(default_factory=list)
    truth_active_ids: List[str] = field(default_factory=list)
    outbox_ids: List[str] = field(default_factory=list)
    qdrant_point_ids: List[str] = field(default_factory=list)

@dataclass
class RetrievalTrace:
    """R 层（召回）追踪信息"""
    retrieval_candidate_ids: List[str] = field(default_factory=list)
    hardfilter_accepted_ids: List[str] = field(default_factory=list)
    reranked_ids: List[str] = field(default_factory=list)
    evidence_memory_ids: List[str] = field(default_factory=list)

@dataclass
class GenerationTrace:
    """G 层（生成）追踪信息"""
    critical_profile_ids: List[str] = field(default_factory=list)
    policy_rule_ids: List[str] = field(default_factory=list)
    final_prompt_hash: str = ""
    guard_decision_id: Optional[str] = None
    answer_sha256: str = ""

@dataclass
class JudgeTrace:
    """J 层（评分）追踪信息"""
    judge_version: str = "1.0"
    score: Optional[float] = None

@dataclass
class ChainTrace:
    """完整的链路追踪信息"""
    write: Optional[WriteTrace] = None
    retrieval: Optional[RetrievalTrace] = None
    generation: Optional[GenerationTrace] = None
    judge: Optional[JudgeTrace] = None
    
    def to_dict(self) -> dict:
        """转为字典"""
        result = {}
        if self.write:
            result["write"] = {
                "extractor_candidate_ids": self.write.extractor_candidate_ids,
                "truth_aggregate_ids": self.write.truth_aggregate_ids,
                "truth_active_ids": self.write.truth_active_ids,
                "outbox_ids": self.write.outbox_ids,
                "qdrant_point_ids": self.write.qdrant_point_ids
            }
        else:
            result["write"] = None
            
        if self.retrieval:
            result["retrieval"] = {
                "retrieval_candidate_ids": self.retrieval.retrieval_candidate_ids,
                "hardfilter_accepted_ids": self.retrieval.hardfilter_accepted_ids,
                "reranked_ids": self.retrieval.reranked_ids,
                "evidence_memory_ids": self.retrieval.evidence_memory_ids
            }
        else:
            result["retrieval"] = None
            
        if self.generation:
            result["generation"] = {
                "critical_profile_ids": self.generation.critical_profile_ids,
                "policy_rule_ids": self.generation.policy_rule_ids,
                "final_prompt_hash": self.generation.final_prompt_hash,
                "guard_decision_id": self.generation.guard_decision_id,
                "answer_sha256": self.generation.answer_sha256
            }
        else:
            result["generation"] = None
            
        if self.judge:
            result["judge"] = {
                "judge_version": self.judge.judge_version,
                "score": self.judge.score
            }
        else:
            result["judge"] = None
            
        return result
