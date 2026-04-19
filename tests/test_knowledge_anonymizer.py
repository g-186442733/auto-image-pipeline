"""anonymize_knowledge 单元测试 — TDD RED→GREEN"""

import pytest

from pipeline.models.knowledge_entry import KnowledgeEntry
from pipeline.layers.knowledge_anonymizer import anonymize_knowledge


def _make_entry(**kw) -> KnowledgeEntry:
    """创建一个不需要数据库的 KnowledgeEntry 实例"""
    defaults = dict(
        id=1,
        source_project_id=10,
        category="qa_lesson",
        title="测试标题",
        content="通用内容",
        tags="tag1,tag2",
        usage_count=0,
    )
    defaults.update(kw)
    e = KnowledgeEntry.__new__(KnowledgeEntry)
    e.__dict__.update(defaults)
    return e


# ---------- 品牌名替换 ----------
class TestBrandAnonymize:
    def test_brand_replaced_in_content(self):
        entry = _make_entry(content="推荐使用 Nike 风格配色")
        result = anonymize_knowledge(entry, brand_list=["Nike"])
        assert "Nike" not in result.__dict__["content"]
        assert "[BRAND]" in result.__dict__["content"]

    def test_brand_replaced_in_title(self):
        entry = _make_entry(title="Nike 产品图规范")
        result = anonymize_knowledge(entry, brand_list=["Nike"])
        assert "Nike" not in result.__dict__["title"]
        assert "[BRAND]" in result.__dict__["title"]

    def test_multiple_brands(self):
        entry = _make_entry(content="Nike 和 Adidas 都要求白底")
        result = anonymize_knowledge(entry, brand_list=["Nike", "Adidas"])
        assert "Nike" not in result.__dict__["content"]
        assert "Adidas" not in result.__dict__["content"]

    def test_brand_case_insensitive(self):
        entry = _make_entry(content="使用 nike 配色方案")
        result = anonymize_knowledge(entry, brand_list=["Nike"])
        assert (
            "nike" not in result.__dict__["content"].lower()
            or "[BRAND]" in result.__dict__["content"]
        )


# ---------- 订单号替换 ----------
class TestOrderAnonymize:
    def test_order_with_hash(self):
        entry = _make_entry(content="参考订单 #ORD-123 的设置")
        result = anonymize_knowledge(entry, brand_list=[])
        assert "#ORD-123" not in result.__dict__["content"]
        assert "[ORDER_ID]" in result.__dict__["content"]

    def test_order_without_hash(self):
        entry = _make_entry(content="订单 ORD-99001 已完成")
        result = anonymize_knowledge(entry, brand_list=[])
        assert "ORD-99001" not in result.__dict__["content"]
        assert "[ORDER_ID]" in result.__dict__["content"]


# ---------- 路径替换 ----------
class TestPathAnonymize:
    def test_simple_path(self):
        entry = _make_entry(content="图片保存在 /data/img.png")
        result = anonymize_knowledge(entry, brand_list=[])
        assert "/data/img.png" not in result.__dict__["content"]
        assert "[PATH]" in result.__dict__["content"]

    def test_nested_path(self):
        entry = _make_entry(content="模板位于 /usr/local/templates/main.psd")
        result = anonymize_knowledge(entry, brand_list=[])
        assert "/usr/local/templates/main.psd" not in result.__dict__["content"]
        assert "[PATH]" in result.__dict__["content"]


# ---------- 混合文本 ----------
class TestMixedAnonymize:
    def test_all_patterns_replaced(self):
        entry = _make_entry(
            content="Nike 订单 #ORD-456 的素材放在 /assets/nike/hero.jpg"
        )
        result = anonymize_knowledge(entry, brand_list=["Nike"])
        assert "Nike" not in result.__dict__["content"]
        assert "#ORD-456" not in result.__dict__["content"]
        assert "/assets/nike/hero.jpg" not in result.__dict__["content"]
        assert "[BRAND]" in result.__dict__["content"]
        assert "[ORDER_ID]" in result.__dict__["content"]
        assert "[PATH]" in result.__dict__["content"]


# ---------- 安全文本不变 ----------
class TestSafeText:
    def test_no_sensitive_data_unchanged(self):
        entry = _make_entry(content="通用说明")
        result = anonymize_knowledge(entry, brand_list=[])
        assert result.__dict__["content"] == "通用说明"

    def test_tags_preserved(self):
        entry = _make_entry(content="通用说明", tags="prompt,style")
        result = anonymize_knowledge(entry, brand_list=[])
        assert result.__dict__["tags"] == "prompt,style"


# ---------- 不可变性 ----------
class TestImmutability:
    def test_original_entry_unchanged(self):
        entry = _make_entry(content="Nike 订单 #ORD-1")
        original_content = entry.__dict__["content"]
        anonymize_knowledge(entry, brand_list=["Nike"])
        assert entry.__dict__["content"] == original_content
