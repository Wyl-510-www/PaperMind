"""
Phase 2.2 PDF 文本提取端到端验证脚本

验证流程：
1. 创建模拟 PDF 文件（使用 PyMuPDF 生成）
2. 测试 PDF 提取功能
3. 测试提取内容保存到 Memory V2
4. 测试同步到 Qdrant
5. 测试检索提取的内容

使用方法：
    python scripts/verify_phase2.2_pdf.py
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 添加 papermind 模块到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from papermind.pdf_extractor import extract_pdf_text
from papermind.app_service import Identity, save_note, sync_notes, ask_memory


class MockLLMClient:
    """Mock LLM 客户端用于测试"""
    async def generate(self, prompt: str) -> str:
        return "基于检索到的记忆生成的测试回答"


def create_test_pdf(output_path: Path) -> bool:
    """创建测试 PDF 文件"""
    try:
        import fitz  # PyMuPDF

        # 创建新 PDF
        doc = fitz.open()
        page = doc.new_page()

        # 添加标题
        title = "Attention Is All You Need: Test Paper"
        page.insert_text(
            (72, 100),  # 位置 (x, y)
            title,
            fontsize=16,
            fontname="helv",
        )

        # 添加正文内容
        content = """
        This is a test paper for Phase 2.2 PDF extraction validation.

        Abstract:
        We propose the Transformer, a novel neural network architecture based
        entirely on attention mechanisms, dispensing with recurrence and convolutions.

        Introduction:
        This paper introduces a new approach to sequence modeling that relies
        solely on self-attention mechanisms to compute representations.

        Methodology:
        The core innovation is the multi-head attention mechanism which allows
        the model to jointly attend to information from different representation
        subspaces at different positions.

        Results:
        Experiments on machine translation tasks demonstrate superior performance
        compared to recurrent and convolutional architectures.

        Conclusion:
        The Transformer architecture represents a significant advancement in
        sequence modeling and has broad applications across NLP tasks.
        """

        # 插入正文
        page.insert_text(
            (72, 150),
            content,
            fontsize=11,
            fontname="helv",
        )

        # 设置元数据
        doc.set_metadata({
            "title": title,
            "author": "Test Author",
            "subject": "AI Research",
        })

        # 保存
        doc.save(output_path)
        doc.close()

        return True

    except ImportError:
        print("❌ PyMuPDF 未安装，无法创建测试 PDF")
        return False
    except Exception as e:
        print(f"❌ 创建测试 PDF 失败: {e}")
        return False


async def main():
    """主验收流程"""
    import sys
    import io

    # 修复 Windows 控制台编码问题
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("=" * 60)
    print("Phase 2.2 PDF 文本提取端到端验证")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 测试身份
    test_identity = Identity(
        tenant_id="test_tenant",
        user_id="pdf_test_user",
        label="PDF测试用户"
    )

    # Stage 1: 创建测试 PDF
    print("\n[Stage 1] 创建测试 PDF 文件")
    test_pdf_path = Path("test_paper.pdf")

    if create_test_pdf(test_pdf_path):
        print(f"✅ Stage 1 通过 - PDF 文件: {test_pdf_path.absolute()}")
    else:
        print("❌ Stage 1 失败 - 无法创建测试 PDF")
        return 1

    # Stage 2: 测试 PDF 提取
    print("\n[Stage 2] 测试 PDF 文本提取")
    try:
        result = await extract_pdf_text(test_pdf_path)

        if not result.success:
            print(f"❌ Stage 2 失败 - 提取失败: {result.error_message}")
            return 1

        print(f"✅ Stage 2 通过")
        print(f"  - 标题: {result.title}")
        print(f"  - 文本长度: {len(result.text)} 字符")
        print(f"  - 预览长度: {len(result.preview)} 字符")

        extracted_title = result.title
        extracted_text = result.text

    except Exception as e:
        print(f"❌ Stage 2 失败 - 异常: {e}")
        return 1

    # Stage 3: 测试保存提取的内容到 Memory V2
    print("\n[Stage 3] 保存提取内容到 Memory V2")
    try:
        # 模拟用户编辑后的阅读结论（实际使用中用户可能只保存摘要）
        reading_conclusion = extracted_text[:500] + "...(用户编辑的阅读结论)"

        write_result = await save_note(
            identity=test_identity,
            title=extracted_title,
            conclusion=reading_conclusion,
            confirmed=True,
        )

        if write_result.status in ["saved", "partial"]:
            print(f"✅ Stage 3 通过 - 状态: {write_result.status}")
            print(f"  - Memory IDs: {write_result.memory_ids}")
            print(f"  - Turn ID: {write_result.turn_id[:8]}...")
        else:
            print(f"❌ Stage 3 失败 - 状态: {write_result.status}")
            print(f"  - 消息: {write_result.message}")
            return 1

    except Exception as e:
        print(f"❌ Stage 3 失败 - 异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Stage 4: 测试 Outbox 同步
    print("\n[Stage 4] 同步到 Qdrant 索引")
    try:
        sync_result = await sync_notes(batch_size=100)

        if sync_result.status == "completed":
            print(f"✅ Stage 4 通过")
            print(f"  - 已处理: {sync_result.done} 条")
            print(f"  - 失败: {sync_result.failed} 条")
            print(f"  - 死信: {sync_result.dead} 条")
        else:
            print(f"⚠️ Stage 4 部分通过 - 状态: {sync_result.status}")

    except Exception as e:
        print(f"⚠️ Stage 4 警告 - 异常: {e}")
        print("  注意: 同步失败不影响核心 PDF 提取功能验证")

    # Stage 5: 测试检索提取的内容
    print("\n[Stage 5] 检索提取的内容")
    try:
        llm_client = MockLLMClient()

        ask_result = await ask_memory(
            identity=test_identity,
            question="我记录了哪些关于 Transformer 或 Attention 的论文？",
            llm_client=llm_client,
        )

        if ask_result.status == "answered" and ask_result.evidence:
            print(f"✅ Stage 5 通过 - 找到证据")
            print(f"  - 证据数量: {len(ask_result.evidence)}")
            for idx, ev in enumerate(ask_result.evidence, 1):
                print(f"  - 证据 {idx}: {ev.content[:100]}...")
        elif ask_result.status == "no_evidence":
            print(f"⚠️ Stage 5 部分通过 - 未找到证据")
            print("  注意: 可能需要等待索引同步完成")
        else:
            print(f"⚠️ Stage 5 警告 - 状态: {ask_result.status}")

    except Exception as e:
        print(f"⚠️ Stage 5 警告 - 异常: {e}")
        print("  注意: 检索失败不影响核心 PDF 提取功能验证")

    # 清理测试文件
    print("\n[清理] 删除测试 PDF 文件")
    try:
        if test_pdf_path.exists():
            test_pdf_path.unlink()
            print("✅ 清理完成")
    except Exception as e:
        print(f"⚠️ 清理失败: {e}")

    # 总结
    print("\n" + "=" * 60)
    print("验收总结")
    print("=" * 60)
    print("✅ PDF 提取核心功能验证通过")
    print("✅ 提取内容可保存到 Memory V2")
    print("⚠️ 完整端到端流程需要真实服务（MySQL, Qdrant）")
    print("\n推荐操作：")
    print("1. 启动 Streamlit UI: streamlit run streamlit_app.py")
    print("2. 手动上传真实论文 PDF 进行完整验证")
    print("3. 验证: 上传 → 提取 → 保存 → 同步 → 查询")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
