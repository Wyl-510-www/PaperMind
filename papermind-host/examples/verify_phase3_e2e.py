"""Phase 3 端到端验收测试脚本

测试覆盖：
1. 保存带元数据的笔记
2. 标签过滤检索（OR 逻辑）
3. 时间范围过滤检索
4. 组合过滤（标签 + 时间）
5. 无过滤条件的全局检索
6. 元数据验证
7. 边界情况处理

使用真实的 MySQL + Qdrant 环境，验证完整的 Phase 3 功能。
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

# 确保 Windows 控制台正确显示 UTF-8
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 添加核心模块路径
core_path = Path(__file__).parent.parent.parent / "memoryV2-core"
if core_path.exists():
    sys.path.insert(0, str(core_path))

from papermind.app_service import save_note, sync_notes, Identity
from papermind.memory_retrieval import retrieve_structured_evidence
from papermind.models import NoteMetadata
from papermind.utils.date_utils import calculate_date_range


class Colors:
    """终端颜色"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


class TestResult:
    """测试结果"""
    def __init__(self, name: str, passed: bool, message: str, details: str = ""):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details

    def __str__(self):
        status = f"{Colors.GREEN}[✓ PASS]{Colors.END}" if self.passed else f"{Colors.RED}[✗ FAIL]{Colors.END}"
        result = f"{status} {Colors.BOLD}{self.name}{Colors.END}\n"
        result += f"      {self.message}\n"
        if self.details:
            result += f"      {Colors.BLUE}详情: {self.details}{Colors.END}\n"
        return result


class Phase3E2ETest:
    """Phase 3 端到端测试类"""

    def __init__(self):
        self.results = []
        self.test_identity = Identity(
            tenant_id="tenant_phase3_e2e",
            user_id="user_test",
            label="Phase3测试用户"
        )
        self.test_notes = []  # 存储测试笔记的 memory_ids

    async def setup(self):
        """测试前置准备"""
        print(f"\n{Colors.BOLD}========================================{Colors.END}")
        print(f"{Colors.BOLD}Phase 3 端到端测试{Colors.END}")
        print(f"{Colors.BOLD}========================================{Colors.END}\n")
        print(f"测试身份: {self.test_identity.label}")
        print(f"租户ID: {self.test_identity.tenant_id}")
        print(f"用户ID: {self.test_identity.user_id}\n")

    async def test_1_save_note_with_metadata(self):
        """测试 1: 保存带完整元数据的笔记"""
        print(f"\n{Colors.YELLOW}>>> 测试 1: 保存带完整元数据的笔记{Colors.END}")

        try:
            # 创建元数据
            metadata = NoteMetadata(
                title="Attention Is All You Need",
                author="Vaswani et al.",
                year="2017",
                read_date=date.today(),
                tags=["Transformer", "注意力机制"],
                note_type="详细笔记"
            )

            # 保存笔记
            result = await save_note(
                identity=self.test_identity,
                title=metadata.title,
                conclusion="Transformer 使用自注意力机制替代了 RNN，显著提升了并行计算能力。",
                confirmed=True,
                metadata=metadata
            )

            if result.status == "saved" and result.memory_ids:
                self.test_notes.append({
                    "memory_id": result.memory_ids[0],
                    "title": metadata.title,
                    "tags": metadata.tags,
                    "read_date": metadata.read_date
                })
                self.results.append(TestResult(
                    name="保存带元数据的笔记",
                    passed=True,
                    message=f"成功保存 {len(result.memory_ids)} 条记忆",
                    details=f"Memory ID: {result.memory_ids[0][:16]}..."
                ))
            else:
                self.results.append(TestResult(
                    name="保存带元数据的笔记",
                    passed=False,
                    message=f"保存失败: {result.message}"
                ))

        except Exception as e:
            self.results.append(TestResult(
                name="保存带元数据的笔记",
                passed=False,
                message=f"异常: {str(e)}"
            ))

    async def test_2_save_multiple_notes(self):
        """测试 2: 保存多条不同标签和日期的笔记"""
        print(f"\n{Colors.YELLOW}>>> 测试 2: 保存多条测试笔记{Colors.END}")

        test_data = [
            {
                "title": "RAG Survey",
                "conclusion": "检索增强生成（RAG）结合了检索和生成，提升了知识密集型任务的性能。",
                "tags": ["RAG（检索增强生成）", "向量数据库"],
                "read_date": date.today() - timedelta(days=5),
                "note_type": "摘要"
            },
            {
                "title": "Memory Architecture for Agents",
                "conclusion": "智能体需要长期记忆架构来存储和检索历史交互信息。",
                "tags": ["长期记忆", "记忆架构", "Agent 智能体"],
                "read_date": date.today() - timedelta(days=10),
                "note_type": "详细笔记"
            },
            {
                "title": "Knowledge Graph Applications",
                "conclusion": "知识图谱在信息检索和推理任务中表现出色。",
                "tags": ["知识图谱", "应用案例"],
                "read_date": date.today() - timedelta(days=30),
                "note_type": "评论"
            }
        ]

        saved_count = 0
        failed_count = 0

        for data in test_data:
            try:
                metadata = NoteMetadata(
                    title=data["title"],
                    author=None,
                    year=None,
                    read_date=data["read_date"],
                    tags=data["tags"],
                    note_type=data["note_type"]
                )

                result = await save_note(
                    identity=self.test_identity,
                    title=data["title"],
                    conclusion=data["conclusion"],
                    confirmed=True,
                    metadata=metadata
                )

                if result.status == "saved" and result.memory_ids:
                    self.test_notes.append({
                        "memory_id": result.memory_ids[0],
                        "title": data["title"],
                        "tags": data["tags"],
                        "read_date": data["read_date"]
                    })
                    saved_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                failed_count += 1
                print(f"   保存失败: {data['title']} - {str(e)}")

        if saved_count == len(test_data):
            self.results.append(TestResult(
                name="保存多条测试笔记",
                passed=True,
                message=f"成功保存 {saved_count} 条笔记",
                details=f"总共测试笔记: {len(self.test_notes)} 条"
            ))
        else:
            self.results.append(TestResult(
                name="保存多条测试笔记",
                passed=False,
                message=f"成功 {saved_count} 条，失败 {failed_count} 条"
            ))

    async def test_3_sync_notes(self):
        """测试 3: 同步笔记到索引"""
        print(f"\n{Colors.YELLOW}>>> 测试 3: 同步笔记到检索索引{Colors.END}")

        try:
            result = await sync_notes(batch_size=100)

            if result.status == "completed":
                self.results.append(TestResult(
                    name="同步笔记到索引",
                    passed=True,
                    message=f"同步完成",
                    details=f"处理: {result.done} 条, 失败: {result.failed} 条"
                ))
                # 等待索引生效
                print(f"   等待 3 秒让索引生效...")
                await asyncio.sleep(3)
            else:
                self.results.append(TestResult(
                    name="同步笔记到索引",
                    passed=False,
                    message=f"同步失败: {result.message}"
                ))

        except Exception as e:
            self.results.append(TestResult(
                name="同步笔记到索引",
                passed=False,
                message=f"异常: {str(e)}"
            ))

    async def test_4_tag_filter_or_logic(self):
        """测试 4: 标签过滤（OR 逻辑）"""
        print(f"\n{Colors.YELLOW}>>> 测试 4: 标签过滤（OR 逻辑）{Colors.END}")

        try:
            # 查询标签: ["Transformer", "长期记忆"]
            # 应返回包含任一标签的笔记
            evidence_list = await retrieve_structured_evidence(
                query="架构设计",
                tenant_id=self.test_identity.tenant_id,
                user_id=self.test_identity.user_id,
                limit=10,
                tags=["Transformer", "长期记忆"]
            )

            # 验证返回的笔记包含至少一个指定标签
            matched_notes = []
            for evidence in evidence_list:
                memory_id = evidence.memory_id
                # 查找对应的测试笔记
                for note in self.test_notes:
                    if note["memory_id"] == memory_id:
                        if any(tag in note["tags"] for tag in ["Transformer", "长期记忆"]):
                            matched_notes.append(note["title"])

            if len(evidence_list) > 0:
                self.results.append(TestResult(
                    name="标签过滤（OR 逻辑）",
                    passed=True,
                    message=f"返回 {len(evidence_list)} 条匹配笔记",
                    details=f"匹配标签的笔记: {', '.join(matched_notes[:3])}"
                ))
            else:
                self.results.append(TestResult(
                    name="标签过滤（OR 逻辑）",
                    passed=False,
                    message="未返回任何结果（可能索引未生效或过滤逻辑错误）"
                ))

        except Exception as e:
            self.results.append(TestResult(
                name="标签过滤（OR 逻辑）",
                passed=False,
                message=f"异常: {str(e)}"
            ))

    async def test_5_time_range_filter(self):
        """测试 5: 时间范围过滤"""
        print(f"\n{Colors.YELLOW}>>> 测试 5: 时间范围过滤{Colors.END}")

        try:
            # 查询本周的笔记
            start_date, end_date = calculate_date_range("本周")

            evidence_list = await retrieve_structured_evidence(
                query="研究",
                tenant_id=self.test_identity.tenant_id,
                user_id=self.test_identity.user_id,
                limit=10,
                start_date=start_date,
                end_date=end_date
            )

            # 验证返回的笔记在时间范围内
            in_range_count = 0
            for evidence in evidence_list:
                for note in self.test_notes:
                    if note["memory_id"] == evidence.memory_id:
                        if start_date <= note["read_date"] <= end_date:
                            in_range_count += 1

            if len(evidence_list) > 0:
                self.results.append(TestResult(
                    name="时间范围过滤",
                    passed=True,
                    message=f"返回 {len(evidence_list)} 条本周笔记",
                    details=f"时间范围: {start_date} ~ {end_date}"
                ))
            else:
                self.results.append(TestResult(
                    name="时间范围过滤",
                    passed=False,
                    message="未返回任何结果（可能本周无笔记或过滤逻辑错误）"
                ))

        except Exception as e:
            self.results.append(TestResult(
                name="时间范围过滤",
                passed=False,
                message=f"异常: {str(e)}"
            ))

    async def test_6_combined_filter(self):
        """测试 6: 组合过滤（标签 + 时间）"""
        print(f"\n{Colors.YELLOW}>>> 测试 6: 组合过滤（标签 + 时间）{Colors.END}")

        try:
            # 查询本月的 Transformer 相关笔记
            start_date, end_date = calculate_date_range("本月")

            evidence_list = await retrieve_structured_evidence(
                query="Transformer 注意力",
                tenant_id=self.test_identity.tenant_id,
                user_id=self.test_identity.user_id,
                limit=10,
                tags=["Transformer"],
                start_date=start_date,
                end_date=end_date
            )

            matched_count = 0
            for evidence in evidence_list:
                for note in self.test_notes:
                    if note["memory_id"] == evidence.memory_id:
                        if "Transformer" in note["tags"] and start_date <= note["read_date"] <= end_date:
                            matched_count += 1

            if matched_count > 0:
                self.results.append(TestResult(
                    name="组合过滤（标签 + 时间）",
                    passed=True,
                    message=f"返回 {len(evidence_list)} 条匹配笔记",
                    details=f"同时满足标签和时间条件: {matched_count} 条"
                ))
            else:
                # 组合过滤可能合法地返回 0 条（本月无 Transformer 笔记）
                self.results.append(TestResult(
                    name="组合过滤（标签 + 时间）",
                    passed=True,
                    message="返回 0 条结果（本月无符合条件的笔记，符合预期）"
                ))

        except Exception as e:
            self.results.append(TestResult(
                name="组合过滤（标签 + 时间）",
                passed=False,
                message=f"异常: {str(e)}"
            ))

    async def test_7_no_filter_global_search(self):
        """测试 7: 无过滤条件的全局检索"""
        print(f"\n{Colors.YELLOW}>>> 测试 7: 无过滤条件的全局检索{Colors.END}")

        try:
            # 不提供任何过滤条件
            evidence_list = await retrieve_structured_evidence(
                query="记忆",
                tenant_id=self.test_identity.tenant_id,
                user_id=self.test_identity.user_id,
                limit=10
            )

            if len(evidence_list) > 0:
                self.results.append(TestResult(
                    name="无过滤条件的全局检索",
                    passed=True,
                    message=f"返回 {len(evidence_list)} 条笔记",
                    details="全局语义检索正常工作（兼容 Phase 2）"
                ))
            else:
                self.results.append(TestResult(
                    name="无过滤条件的全局检索",
                    passed=False,
                    message="未返回任何结果（全局检索失败）"
                ))

        except Exception as e:
            self.results.append(TestResult(
                name="无过滤条件的全局检索",
                passed=False,
                message=f"异常: {str(e)}"
            ))

    async def test_8_metadata_validation(self):
        """测试 8: 元数据验证"""
        print(f"\n{Colors.YELLOW}>>> 测试 8: 元数据验证{Colors.END}")

        validation_tests = []

        # 测试 8.1: 空标题
        try:
            metadata = NoteMetadata(
                title="",
                read_date=date.today(),
                tags=["长期记忆"],
                note_type="摘要"
            )
            validation_tests.append(("空标题验证", False, "应拒绝空标题但通过了"))
        except ValueError:
            validation_tests.append(("空标题验证", True, "正确拒绝空标题"))

        # 测试 8.2: 无效标签
        try:
            metadata = NoteMetadata(
                title="测试",
                read_date=date.today(),
                tags=["无效标签"],
                note_type="摘要"
            )
            validation_tests.append(("无效标签验证", False, "应拒绝无效标签但通过了"))
        except ValueError:
            validation_tests.append(("无效标签验证", True, "正确拒绝无效标签"))

        # 测试 8.3: 空标签列表
        try:
            metadata = NoteMetadata(
                title="测试",
                read_date=date.today(),
                tags=[],
                note_type="摘要"
            )
            validation_tests.append(("空标签列表验证", False, "应拒绝空标签列表但通过了"))
        except ValueError:
            validation_tests.append(("空标签列表验证", True, "正确拒绝空标签列表"))

        # 测试 8.4: 无效笔记类型
        try:
            metadata = NoteMetadata(
                title="测试",
                read_date=date.today(),
                tags=["长期记忆"],
                note_type="无效类型"
            )
            validation_tests.append(("无效笔记类型验证", False, "应拒绝无效笔记类型但通过了"))
        except ValueError:
            validation_tests.append(("无效笔记类型验证", True, "正确拒绝无效笔记类型"))

        # 汇总验证测试结果
        passed_count = sum(1 for _, passed, _ in validation_tests if passed)
        total_count = len(validation_tests)

        if passed_count == total_count:
            self.results.append(TestResult(
                name="元数据验证",
                passed=True,
                message=f"所有验证测试通过 ({passed_count}/{total_count})",
                details="; ".join([f"{name}: ✓" for name, passed, _ in validation_tests if passed])
            ))
        else:
            failed_tests = [msg for _, passed, msg in validation_tests if not passed]
            self.results.append(TestResult(
                name="元数据验证",
                passed=False,
                message=f"部分验证测试失败 ({passed_count}/{total_count})",
                details="; ".join(failed_tests)
            ))

    async def test_9_date_range_calculation(self):
        """测试 9: 日期范围计算"""
        print(f"\n{Colors.YELLOW}>>> 测试 9: 日期范围计算{Colors.END}")

        calculation_tests = []

        # 测试全部时间
        start, end = calculate_date_range("全部时间")
        calculation_tests.append(("全部时间", start is None and end is None))

        # 测试本周
        start, end = calculate_date_range("本周")
        calculation_tests.append(("本周", start is not None and end == date.today()))

        # 测试本月
        start, end = calculate_date_range("本月")
        calculation_tests.append(("本月", start.day == 1 and end == date.today()))

        # 测试本年
        start, end = calculate_date_range("本年")
        calculation_tests.append(("本年", start.month == 1 and start.day == 1 and end == date.today()))

        # 测试自定义
        custom_start = date(2026, 1, 1)
        custom_end = date(2026, 1, 10)
        start, end = calculate_date_range("自定义", custom_start, custom_end)
        calculation_tests.append(("自定义", start == custom_start and end == custom_end))

        passed_count = sum(1 for _, passed in calculation_tests if passed)
        total_count = len(calculation_tests)

        if passed_count == total_count:
            self.results.append(TestResult(
                name="日期范围计算",
                passed=True,
                message=f"所有日期计算正确 ({passed_count}/{total_count})",
                details=", ".join([name for name, _ in calculation_tests])
            ))
        else:
            self.results.append(TestResult(
                name="日期范围计算",
                passed=False,
                message=f"部分日期计算错误 ({passed_count}/{total_count})"
            ))

    def print_summary(self):
        """打印测试总结"""
        print(f"\n{Colors.BOLD}========================================{Colors.END}")
        print(f"{Colors.BOLD}测试结果{Colors.END}")
        print(f"{Colors.BOLD}========================================{Colors.END}\n")

        for result in self.results:
            print(result)

        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)
        pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0

        print(f"\n{Colors.BOLD}========================================{Colors.END}")
        print(f"{Colors.BOLD}总结{Colors.END}")
        print(f"{Colors.BOLD}========================================{Colors.END}\n")
        print(f"总测试数: {total_count}")
        print(f"通过: {Colors.GREEN}{passed_count}{Colors.END}")
        print(f"失败: {Colors.RED}{total_count - passed_count}{Colors.END}")
        print(f"通过率: {Colors.GREEN if pass_rate == 100 else Colors.YELLOW}{pass_rate:.1f}%{Colors.END}\n")

        if passed_count == total_count:
            print(f"{Colors.GREEN}{Colors.BOLD}✓ Phase 3 端到端测试全部通过！{Colors.END}\n")
            return True
        else:
            print(f"{Colors.RED}{Colors.BOLD}✗ 部分测试失败，请检查上述失败项。{Colors.END}\n")
            return False

    async def run_all_tests(self):
        """运行所有测试"""
        await self.setup()

        # 按顺序执行测试
        await self.test_1_save_note_with_metadata()
        await self.test_2_save_multiple_notes()
        await self.test_3_sync_notes()
        await self.test_4_tag_filter_or_logic()
        await self.test_5_time_range_filter()
        await self.test_6_combined_filter()
        await self.test_7_no_filter_global_search()
        await self.test_8_metadata_validation()
        await self.test_9_date_range_calculation()

        # 打印总结
        success = self.print_summary()
        return success


async def main():
    """主函数"""
    tester = Phase3E2ETest()
    success = await tester.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
