"""查询路由：判断本轮 query 需要哪些记忆类型。

不是每一轮都必须塞满 Top-5 用户记忆（原方案 6.1）。
QueryRouter 判断本轮该查什么类型、各类 top_k 多少，或者跳过检索（普通寒暄）。

遵循 ADR 0006：不确定时倾向多返回一类而非漏（宁可多召回也不漏召回）。
检索链路的代价结构与写入端相反：漏召回=用户直接可感的失忆，
误召回有 hard_filter + Claim Guard 两道兜底。

见 ADR 0005（模块命名）、ADR 0006（检索取向）。
"""

from __future__ import annotations

import re

from ..contracts import MemoryType, RetrievalPlan


# 默认每类 top_k（可后续改为配置）
# ADR 0006: 检索侧宁可多召回，不确定时多返回而非漏
# 修复：添加 BEHAVIOR_POLICY 和 ENTITY_RELATION 支持
DEFAULT_TOP_K = {
    MemoryType.SEMANTIC: 50,
    MemoryType.EPISODIC: 10,
    MemoryType.STATE: 5,
    MemoryType.TASK: 5,
    MemoryType.BEHAVIOR_POLICY: 20,      # 行为策略：称呼偏好、沟通风格等
    MemoryType.ENTITY_RELATION: 30,      # 实体关系：人名、地名、机构等
}


class QueryRouter:
    """查询路由器（纯函数，无 I/O）。

    根据 query 文本判断本轮需要哪些记忆类型，产出 RetrievalPlan。
    轻规则实现——不追求 100% 准确，不确定时倾向多查（ADR 0006）。
    """

    def route(self, query: str) -> RetrievalPlan:
        """判断本轮查什么，返回 RetrievalPlan。"""
        query_lower = query.strip().lower()

        # 普通寒暄 → skip_retrieval
        if self._is_greeting(query_lower):
            return RetrievalPlan(skip_retrieval=True)

        memory_types: set[MemoryType] = set()

        # 修复：behavior_policy 查询检测（称呼、沟通风格、行为偏好）
        if self._is_behavior_policy_query(query_lower):
            memory_types.add(MemoryType.BEHAVIOR_POLICY)

        # 修复：entity_relation 查询检测（人名、关系、地名）
        if self._is_entity_relation_query(query_lower):
            memory_types.add(MemoryType.ENTITY_RELATION)

        # 语义偏好类
        if self._is_preference_query(query_lower):
            memory_types.add(MemoryType.SEMANTIC)

        # 事件类
        if self._is_event_query(query_lower):
            memory_types.add(MemoryType.EPISODIC)

        # 任务/进度类
        if self._is_task_query(query_lower):
            memory_types.add(MemoryType.TASK)
            memory_types.add(MemoryType.STATE)  # task 和 state 常同时查

        # 不确定但有实质内容 → 至少查 semantic（兜底）
        # 修复：同时查 behavior_policy 和 entity_relation 作为兜底
        if not memory_types and len(query_lower) > 3:
            memory_types.add(MemoryType.SEMANTIC)
            memory_types.add(MemoryType.BEHAVIOR_POLICY)
            memory_types.add(MemoryType.ENTITY_RELATION)

        # 组装 per_type_top_k
        per_type_top_k = {
            mt.value: DEFAULT_TOP_K.get(mt, 3) for mt in memory_types
        }

        return RetrievalPlan(
            memory_types=memory_types,
            per_type_top_k=per_type_top_k,
            skip_retrieval=(len(memory_types) == 0),
        )

    @staticmethod
    def _is_greeting(query: str) -> bool:
        """判断是否普通寒暄（跳过检索）。"""
        greetings = {"你好", "你好呀", "在吗", "hi", "hello", "哈哈", "嗯", "嗯嗯", "好的"}
        return query in greetings

    @staticmethod
    def _is_behavior_policy_query(query: str) -> bool:
        """判断是否 behavior_policy 查询（称呼偏好、沟通风格、行为习惯）。
        
        修复 case_002: "我现在还应该被叫阿晚吗？"
        """
        patterns = [
            r"(叫|称呼|喊|叫我|称我|叫你)",  # 称呼相关
            r"(应该|可以|能不能|要不要|是否)",  # 行为询问
            r"(风格|方式|习惯|态度|语气)",  # 沟通风格
            r"(不要|别|禁止|拒绝|不想)",  # 行为边界
        ]
        return any(re.search(p, query) for p in patterns)

    @staticmethod
    def _is_entity_relation_query(query: str) -> bool:
        """判断是否 entity_relation 查询（人名、关系、地名、机构）。
        
        修复 case_064: "我在纽约的室友叫什么？"
        修复 case_066: "我在纽约最常一起出门的朋友叫什么？"
        """
        patterns = [
            r"(叫什么|叫啥|名字|姓名)",  # 询问名字
            r"(室友|朋友|同事|邻居|舍友|伙伴|搭档)",  # 关系词
            r"(家人|亲戚|父母|兄弟|姐妹|孩子|爱人)",  # 家庭关系
            r"(老师|同学|学长|学妹|导师)",  # 学校关系
            r"(在.*的|认识的|熟悉的)",  # 关系修饰
            r"(谁|哪位|什么人)",  # 人物询问
        ]
        return any(re.search(p, query) for p in patterns)

    @staticmethod
    def _is_preference_query(query: str) -> bool:
        """判断是否语义偏好类 query（"我喜欢什么""我不吃什么"）。"""
        patterns = [
            r"(喜欢|爱|偏好|倾向|讨厌|不喜欢|不爱)",
            r"(吃|喝|听|看|玩|做)",
            r"(过敏|禁忌|戒)",
        ]
        return any(re.search(p, query) for p in patterns)

    @staticmethod
    def _is_event_query(query: str) -> bool:
        """判断是否事件类 query（"聚会还去吗""上次买的鞋"）。"""
        patterns = [
            r"(上次|上回|那次|那个|之前)",
            r"(聚会|约会|见面|会议|活动|派对)",
            r"(还去|要去|参加)",
            r"(买|订|预约|安排)",
        ]
        return any(re.search(p, query) for p in patterns)

    @staticmethod
    def _is_task_query(query: str) -> bool:
        """判断是否任务/进度类 query（"论文做到哪了""进度怎么样"）。"""
        patterns = [
            r"(论文|项目|作业|任务|工作)",
            r"(进度|进展|完成|做到|状态)",
            r"(怎么样|如何)",
        ]
        return any(re.search(p, query) for p in patterns)
