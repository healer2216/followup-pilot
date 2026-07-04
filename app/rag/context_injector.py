"""RAG: 上下文注入器（Token 预算控制）"""

from typing import List
from app.models import Evidence


class ContextInjector:
    """将证据列表格式化为 LLM 可读的上下文"""
    
    MAX_TOKENS = 3000  # 最大 Token 数（粗略估算：1 token ≈ 2 字符）
    
    def inject(self, evidences: List[Evidence]) -> str:
        """
        将证据列表注入为上下文文本
        
        Args:
            evidences: 证据列表
            
        Returns:
            Formatted context text
        """
        context_parts = []
        total_chars = 0
        
        for i, ev in enumerate(evidences):
            # 格式化单条证据
            snippet = ev.abstract[:300] if ev.abstract else "无摘要"
            part = f"[证据{i+1}] [{ev.grade}级] {ev.title}\n来源：{ev.source.value}\n摘要：{snippet}\n"
            
            # 检查是否超出 Token 限制
            if total_chars + len(part) > self.MAX_TOKENS * 2:
                context_parts.append(f"...（剩余 {len(evidences)-i} 条证据已省略，因超过上下文长度限制）")
                break
            
            context_parts.append(part)
            total_chars += len(part)
        
        return "\n".join(context_parts)
