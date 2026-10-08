"""
测试元数据验证
"""

import pytest
from datetime import date
from pydantic import ValidationError
from papermind.models import NoteMetadata
from papermind.constants import PREDEFINED_TAGS, NOTE_TYPES


class TestNoteMetadata:
    """测试 NoteMetadata 模型验证"""

    def test_valid_metadata(self):
        """测试有效的元数据"""
        metadata = NoteMetadata(
            title="Attention Is All You Need",
            author="Vaswani et al.",
            year="2017",
            read_date=date(2026, 1, 13),
            tags=["Transformer", "注意力机制"],
            note_type="详细笔记",
        )

        assert metadata.title == "Attention Is All You Need"
        assert metadata.author == "Vaswani et al."
        assert metadata.year == "2017"
        assert metadata.read_date == date(2026, 1, 13)
        assert metadata.tags == ["Transformer", "注意力机制"]
        assert metadata.note_type == "详细笔记"

    def test_minimal_metadata(self):
        """测试最小必填字段"""
        metadata = NoteMetadata(
            title="Test Title",
            read_date=date.today(),
            tags=["长期记忆"],
            note_type="摘要",
        )

        assert metadata.title == "Test Title"
        assert metadata.author is None
        assert metadata.year is None

    def test_empty_title(self):
        """测试空标题"""
        with pytest.raises(ValidationError):
            NoteMetadata(
                title="",
                read_date=date.today(),
                tags=["长期记忆"],
                note_type="摘要",
            )

    def test_whitespace_only_title(self):
        """测试仅空格的标题"""
        with pytest.raises(ValidationError):
            NoteMetadata(
                title="   ",
                read_date=date.today(),
                tags=["长期记忆"],
                note_type="摘要",
            )

    def test_empty_tags(self):
        """测试空标签列表"""
        with pytest.raises(ValidationError):
            NoteMetadata(
                title="Test",
                read_date=date.today(),
                tags=[],
                note_type="摘要",
            )

    def test_invalid_tag(self):
        """测试无效标签"""
        with pytest.raises(ValidationError, match="无效标签"):
            NoteMetadata(
                title="Test",
                read_date=date.today(),
                tags=["不存在的标签"],
                note_type="摘要",
            )

    def test_mixed_valid_invalid_tags(self):
        """测试混合有效和无效标签"""
        with pytest.raises(ValidationError, match="无效标签"):
            NoteMetadata(
                title="Test",
                read_date=date.today(),
                tags=["长期记忆", "无效标签"],
                note_type="摘要",
            )

    def test_invalid_note_type(self):
        """测试无效笔记类型"""
        with pytest.raises(ValidationError, match="无效笔记类型"):
            NoteMetadata(
                title="Test",
                read_date=date.today(),
                tags=["长期记忆"],
                note_type="不存在的类型",
            )

    def test_all_valid_tags(self):
        """测试所有预定义标签都有效"""
        for tag in PREDEFINED_TAGS:
            metadata = NoteMetadata(
                title="Test",
                read_date=date.today(),
                tags=[tag],
                note_type="摘要",
            )
            assert tag in metadata.tags

    def test_all_valid_note_types(self):
        """测试所有预定义笔记类型都有效"""
        for note_type in NOTE_TYPES:
            metadata = NoteMetadata(
                title="Test",
                read_date=date.today(),
                tags=["长期记忆"],
                note_type=note_type,
            )
            assert metadata.note_type == note_type

    def test_multiple_tags(self):
        """测试多个标签"""
        tags = ["长期记忆", "Transformer", "RAG（检索增强生成）"]
        metadata = NoteMetadata(
            title="Test",
            read_date=date.today(),
            tags=tags,
            note_type="摘要",
        )
        assert metadata.tags == tags

    def test_title_whitespace_stripped(self):
        """测试标题前后空格被去除"""
        metadata = NoteMetadata(
            title="  Test Title  ",
            read_date=date.today(),
            tags=["长期记忆"],
            note_type="摘要",
        )
        assert metadata.title == "Test Title"

    def test_optional_fields_none(self):
        """测试可选字段为 None"""
        metadata = NoteMetadata(
            title="Test",
            author=None,
            year=None,
            read_date=date.today(),
            tags=["长期记忆"],
            note_type="摘要",
        )
        assert metadata.author is None
        assert metadata.year is None
