"""KnowS Evidence Search 客户端封装。

API: https://api.nullht.com/v1
Sources: paper_en, paper_cn, meeting, guide, trial, package_insert
Rate limit: 匿名 3 QPS / API Key 10 QPS
"""

import asyncio
import os
from typing import Optional

import httpx

from app.models import Evidence, EvidenceSource

DEFAULT_API_ROOT = "https://api.nullht.com/v1"
SERIAL_INTERVAL = 0.4  # seconds

SOURCE_ENDPOINTS = {
    EvidenceSource.PAPER_EN: "/evidences/ai_search_paper_en",
    EvidenceSource.PAPER_CN: "/evidences/ai_search_paper_cn",
    EvidenceSource.MEETING: "/evidences/ai_search_meeting",
    EvidenceSource.GUIDE: "/evidences/ai_search_guide",
    EvidenceSource.TRIAL: "/evidences/ai_search_trial",
    EvidenceSource.PACKAGE_INSERT: "/evidences/ai_search_package_insert",
}


class KnowSClient:
    """KnowS 循证检索客户端"""

    def __init__(
        self,
        api_root: str = DEFAULT_API_ROOT,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_root = api_root.rstrip("/")
        self.api_key = api_key or os.getenv("KNOWS_API_KEY")
        self.timeout = timeout

    async def search(
        self,
        source: EvidenceSource,
        query: str,
        max_results: int = 10,
    ) -> list[Evidence]:
        """
        查询单个证据源。

        Args:
            source: 证据源类型
            query: 查询语句
            max_results: 最大返回条数

        Returns:
            Evidence 列表
        """
        endpoint = SOURCE_ENDPOINTS.get(source)
        if not endpoint:
            raise ValueError(f"Unsupported source: {source}")

        url = f"{self.api_root}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"query": query}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return self._parse_response(data, source, max_results)

    async def search_multi(
        self,
        queries: list[tuple[EvidenceSource, str]],
        interval: float = SERIAL_INTERVAL,
    ) -> list[Evidence]:
        """
        串行查询多个源（避免限流）。

        Args:
            queries: [(source, query), ...]
            interval: 调用间隔（秒）

        Returns:
            所有源的证据合并列表
        """
        all_evidences = []
        for i, (source, query) in enumerate(queries):
            if i > 0:
                await asyncio.sleep(interval)
            try:
                results = await self.search(source, query)
                all_evidences.extend(results)
            except Exception as e:
                # 单源失败不阻断
                print(f"[KnowS] Warning: search failed for {source.value}: {e}")
                continue
        return all_evidences

    async def health_check(self) -> bool:
        """检查 KnowS API 是否可用"""
        try:
            await self.search(EvidenceSource.GUIDE, "test", max_results=1)
            return True
        except Exception:
            return False

    def _parse_response(
        self,
        data: dict,
        source: EvidenceSource,
        max_results: int,
    ) -> list[Evidence]:
        """解析 KnowS 响应"""
        evidences_raw = data.get("evidences", []) or []
        results = []
        for raw in evidences_raw[:max_results]:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            results.append(Evidence(
                id=raw["id"],
                source=source,
                title=raw.get("title", ""),
                abstract=raw.get("abstract"),
                publish_date=raw.get("publish_date"),
                journal=raw.get("journal"),
                doi=raw.get("doi"),
                study_type=raw.get("study_type"),
                impact_factor=raw.get("impact_factor"),
                has_pdf=bool(raw.get("has_pdf", False)),
                organizations=raw.get("organizations", []) or [],
            ))
        return results
