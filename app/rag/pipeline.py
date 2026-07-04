"""RAG: 主编排器（检索增强生成流水线）"""

import asyncio
from typing import List, Tuple
from app.models import DischargeSummary, Evidence, EvidenceSource
from app.tools.knows_search import KnowSClient
from app.tools.llm_gateway import LLMGateway
from app.cache import rag_cache
from .query_builder import QueryBuilder
from .reranker import Reranker
from .context_injector import ContextInjector


class RAGPipeline:
    """RAG Pipeline 编排器"""
    
    def __init__(
        self, 
        knows_client: KnowSClient, 
        llm_client: LLMGateway
    ):
        self.knows = knows_client
        self.query_builder = QueryBuilder()
        self.reranker = Reranker(llm_client)
        self.context_injector = ContextInjector()
    
    async def retrieve(
        self, 
        summary: DischargeSummary,
        top_k: int = 10
    ) -> Tuple[List[Evidence], str]:
        """
        检索并返回重排序后的证据 + 注入的上下文
        
        Args:
            summary: 出院小结
            top_k: 返回 Top-K 证据
            
        Returns:
            (evidences, context_text)
        """
        # Step 0: 检查缓存（基于诊断和用药生成缓存键）
        cache_key_parts = [
            "|".join(sorted(summary.diagnoses)) if summary.diagnoses else "",
            "|".join(sorted([m.name for m in summary.medications])) if summary.medications else ""
        ]
        cached_result = rag_cache.get(*cache_key_parts)
        if cached_result:
            print(f"[RAG] 命中缓存，跳过检索")
            return cached_result
        
        # Step 1: 构建查询
        queries = self.query_builder.build_queries(summary)
        print(f"[RAG] 构建了 {len(queries)} 个查询")
        
        # Step 2: 并行检索（每个查询最多5条结果）
        tasks = [
            self._search_single(source, query)
            for source, query in queries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Step 3: 合并 & 去重
        all_evidences = []
        seen_titles = set()
        for result in results:
            if isinstance(result, Exception):
                print(f"[RAG] Warning: {result}")
                continue
            for ev in result:
                if ev.title not in seen_titles:
                    all_evidences.append(ev)
                    seen_titles.add(ev.title)
        
        print(f"[RAG] 检索到 {len(all_evidences)} 条唯一证据")
        
        # Step 4: 重排序
        if not all_evidences:
            return [], ""
        
        query_text = " ".join([q for _, q in queries[:2]])  # 用前2个查询作为代表
        ranked = await self.reranker.rerank(query_text, all_evidences)
        
        # Step 5: 取 Top-K
        top_evidences = [ev for ev, score in ranked[:top_k]]
        
        # Step 6: 注入上下文
        context = self.context_injector.inject(top_evidences)
        
        # Step 7: 写入缓存
        rag_cache.set(*cache_key_parts, value=(top_evidences, context))
        print(f"[RAG] 结果已缓存")
        
        print(f"[RAG] 最终返回 {len(top_evidences)} 条证据")
        return top_evidences, context
    
    async def _search_single(
        self, 
        source: EvidenceSource, 
        query: str
    ) -> List[Evidence]:
        """单次检索（带异常处理）"""
        try:
            results = await self.knows.search(source, query, max_results=5)
            return results
        except Exception as e:
            raise Exception(f"检索失败 [{source.value}]: {e}")
