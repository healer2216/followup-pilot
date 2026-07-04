"""RAG: 证据重排序器"""

from typing import List, Tuple
from app.models import Evidence
from app.tools.llm_gateway import LLMGateway


class Reranker:
    """证据重排序器（融合评分）"""
    
    def __init__(self, llm_client: LLMGateway):
        self.llm = llm_client
    
    async def rerank(
        self, 
        query: str, 
        evidences: List[Evidence]
    ) -> List[Tuple[Evidence, float]]:
        """
        重排序证据列表（批量 LLM 评分 + 关键词匹配 + 分级）
        """
        if not evidences:
            return []
        
        # 批量 LLM 评分（一次调用评估所有证据）
        llm_scores = await self._batch_llm_judge(query, evidences)
        
        scored = []
        for i, ev in enumerate(evidences):
            vec_score = self._keyword_similarity(query, ev.abstract or "")
            llm_score = llm_scores[i] if i < len(llm_scores) else 0.5
            grade_score = self._grade_to_score(ev.grade)
            final_score = 0.4 * vec_score + 0.4 * llm_score + 0.2 * grade_score
            scored.append((ev, final_score))
        
        return sorted(scored, key=lambda x: x[1], reverse=True)
    
    async def _batch_llm_judge(self, query: str, evidences: List[Evidence]) -> List[float]:
        """批量 LLM 评分（一次调用评估所有证据，大幅提升速度）"""
        if not evidences:
            return []
        
        # 构建批量评分 prompt
        evidence_list = ""
        for i, ev in enumerate(evidences):
            abstract_short = (ev.abstract or "无摘要")[:200]
            evidence_list += f"\n{i+1}. 标题：{ev.title}\n   摘要：{abstract_short}\n"
        
        prompt = f"""请判断以下医学证据与查询的相关性，对每条证据给出0.0-1.0的分数。

查询：{query}

证据列表：{evidence_list}

请严格按以下格式返回分数（每行一个数字，不要有其他文字）：
0.8
0.6
0.9
..."""
        
        try:
            response = await self.llm.chat_completion_with_retry(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            # 解析返回的分数
            scores = []
            for line in response.strip().split('\n'):
                line = line.strip()
                # 提取数字
                import re
                nums = re.findall(r'0?\.?\d+\.?\d*', line)
                if nums:
                    score = float(nums[0])
                    scores.append(max(0.0, min(1.0, score)))
            
            # 补齐不足的分数
            while len(scores) < len(evidences):
                scores.append(0.5)
            
            print(f"[Reranker] 批量评分完成: {len(evidences)} 条证据，1次 LLM 调用")
            return scores[:len(evidences)]
        except Exception as e:
            print(f"[Reranker] 批量 LLM 评分失败: {e}，使用关键词相似度")
            return [self._keyword_similarity(query, ev.abstract or "") for ev in evidences]
    
    def _keyword_similarity(self, query: str, text: str) -> float:
        """
        简化版相似度计算（关键词重叠率）
        
        Args:
            query: 查询文本
            text: 待比较文本
            
        Returns:
            Similarity score (0.0-1.0)
        """
        query_words = set(query.lower().split())
        text_words = set(text.lower().split())
        
        if not query_words or not text_words:
            return 0.0
        
        overlap = len(query_words & text_words)
        return overlap / len(query_words)
    
    async def _llm_judge_relevance(self, query: str, evidence: Evidence) -> float:
        """
        LLM 判断相关性（0-1分）
        
        Args:
            query: 查询文本
            evidence: 证据对象
            
        Returns:
            Relevance score (0.0-1.0)
        """
        prompt = f"""请判断以下医学证据与查询的相关性（0-1分）：

查询：{query}
证据标题：{evidence.title}
证据摘要：{evidence.abstract[:500] if evidence.abstract else "无摘要"}

只返回一个数字（0.0-1.0），不要有其他文字。"""
        
        try:
            response = await self.llm.chat_completion_with_retry(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            score = float(response.strip())
            return max(0.0, min(1.0, score))
        except Exception as e:
            print(f"[Reranker] LLM judge failed: {e}")
            return 0.5  # 默认中等相关性
    
    def _grade_to_score(self, grade: str) -> float:
        """
        证据分级转换为分数
        
        Args:
            grade: 证据分级（A/B/C/D/E）
            
        Returns:
            Score (0.2-1.0)
        """
        grade_map = {
            "A": 1.0,
            "B": 0.8,
            "C": 0.6,
            "D": 0.4,
            "E": 0.2,
        }
        return grade_map.get(grade.upper(), 0.2)
