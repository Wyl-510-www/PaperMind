"""
PaperMind 数据模型

使用 Pydantic 定义数据结构，确保类型安全和验证。
"""

from datetime import date
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

from papermind.constants import PREDEFINED_TAGS, NOTE_TYPES


class NoteMetadata(BaseModel):
    """笔记元数据模型

    Attributes:
        title: 论文标题（必填）
        author: 论文作者（选填）
        year: 发表年份或会议（选填）
        read_date: 阅读日期（必填）
        tags: 标签列表，至少选择1个（必填）
        note_type: 笔记类型（必填）
    """

    title: str = Field(..., min_length=1, description="论文标题")
    author: Optional[str] = Field(None, description="论文作者")
    year: Optional[str] = Field(None, description="发表年份或会议")
    read_date: date = Field(..., description="阅读日期")
    tags: List[str] = Field(..., min_length=1, description="标签列表（至少1个）")
    note_type: str = Field(..., description="笔记类型")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """验证标签是否在预定义列表中"""
        if not v:
            raise ValueError("标签列表不能为空，至少选择1个标签")

        invalid_tags = [tag for tag in v if tag not in PREDEFINED_TAGS]
        if invalid_tags:
            raise ValueError(f"无效标签: {invalid_tags}。必须在预定义列表中选择。")
        return v

    @field_validator("note_type")
    @classmethod
    def validate_note_type(cls, v: str) -> str:
        """验证笔记类型是否有效"""
        if v not in NOTE_TYPES:
            raise ValueError(f"无效笔记类型: {v}。可选值: {NOTE_TYPES}")
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        """验证标题不为空"""
        if not v or not v.strip():
            raise ValueError("论文标题不能为空")
        return v.strip()
