"""RAG: PICO 查询构造器"""

from typing import List, Tuple
from app.models import DischargeSummary, EvidenceSource


class QueryBuilder:
    """从出院小结生成 PICO 查询"""
    
    def build_queries(self, summary: DischargeSummary) -> List[Tuple[EvidenceSource, str]]:
        """
        构建多个检索查询
        
        Returns:
            List of (EvidenceSource, query_text) tuples
        """
        queries = []
        
        # 1. 临床指南查询（每个诊断）
        for diagnosis in summary.diagnoses:
            queries.append((
                EvidenceSource.GUIDE,
                f"{diagnosis} 出院后随访管理指南"
            ))
        
        # 2. 药品说明书查询（每种药物）
        for med in summary.medications:
            queries.append((
                EvidenceSource.PACKAGE_INSERT,
                f"{med.name} {med.dosage} 注意事项 不良反应 用法用量"
            ))
        
        # 3. 中文论文查询
        if summary.diagnoses:
            diagnoses_text = " ".join(summary.diagnoses)
            queries.append((
                EvidenceSource.PAPER_CN,
                f"{diagnoses_text} 出院后康复管理 随访"
            ))
        
        # 4. 英文论文查询
        if summary.diagnoses:
            diagnoses_text = " ".join(summary.diagnoses)
            queries.append((
                EvidenceSource.PAPER_EN,
                f"{diagnoses_text} post-discharge follow-up management"
            ))
        
        return queries
