"""M2: 循证检索服务"""

import asyncio
from app.models import DischargeSummary, Evidence, EvidenceSource
from app.tools.knows_search import KnowSClient


class EvidenceService:
    """KnowS 循证检索服务"""

    SERIAL_INTERVAL = 0.4  # 串行间隔（秒），满足 3 QPS

    def __init__(self, knows_client: KnowSClient):
        self.knows = knows_client

    async def search_for_plan(
        self, summary: DischargeSummary
    ) -> list[Evidence]:
        """
        根据出院小结自动构造多源查询，串行检索。

        查询策略：
        1. guide — 查该病种的随访指南（最高优先级）
        2. package_insert — 查每种药物的说明书
        3. paper_cn — 查中文论文（恢复期管理）
        4. paper_en — 查英文论文（最新循证证据）
        """
        queries = self._build_queries(summary)
        all_evidences: list[Evidence] = []

        for i, (source, query) in enumerate(queries):
            if i > 0:
                await asyncio.sleep(self.SERIAL_INTERVAL)
            try:
                results = await self.knows.search(source, query, max_results=5)
                all_evidences.extend(results)
            except Exception as e:
                print(f"[Evidence] Warning: search failed for {source.value}: {e}")
                continue  # 单源失败不阻断整体

        return all_evidences

    async def search_on_demand(
        self, query: str, sources: list[EvidenceSource] = None
    ) -> list[Evidence]:
        """
        对话中按需补充检索（ChatbotSvc 调用）。
        当患者提到新症状/问题时，动态检索相关证据。
        """
        if sources is None:
            sources = [EvidenceSource.GUIDE, EvidenceSource.PAPER_CN]

        results = []
        for i, source in enumerate(sources):
            if i > 0:
                await asyncio.sleep(self.SERIAL_INTERVAL)
            try:
                evs = await self.knows.search(source, query, max_results=3)
                results.extend(evs[:3])  # 按需检索取 Top 3
            except Exception:
                continue
        return results

    def _build_queries(
        self, summary: DischargeSummary
    ) -> list[tuple[EvidenceSource, str]]:
        """自动构造查询列表"""
        queries = []
        # 修复：使用 diagnoses（复数）而不是 diagnosis
        diagnosis = summary.diagnoses[0] if summary.diagnoses else "未知疾病"

        # 1. 临床指南：病种 + 随访/管理/出院
        queries.append((
            EvidenceSource.GUIDE,
            f"{diagnosis} 出院后随访管理"
        ))

        # 2. 药品说明书：每种药物单独查
        for med in summary.medications:
            queries.append((
                EvidenceSource.PACKAGE_INSERT,
                f"{med.name} 注意事项 不良反应"
            ))

        # 3. 中文论文：病种 + 出院 + 随访
        queries.append((
            EvidenceSource.PAPER_CN,
            f"{diagnosis} 出院后 随访 康复 管理"
        ))

        # 4. 英文论文：英文诊断 + follow-up
        queries.append((
            EvidenceSource.PAPER_EN,
            f"{diagnosis} post-discharge follow-up management guidelines"
        ))

        return queries
