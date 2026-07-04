"""Multi-Agent: 分诊官 Agent"""

import json
from app.models import DischargeSummary
from app.tools.llm_gateway import LLMGateway


class TriageAgent:
    """分诊官 Agent - 分析患者风险，制定检索策略"""
    
    def __init__(self, llm_client: LLMGateway):
        self.llm = llm_client
    
    async def analyze(self, summary: DischargeSummary) -> dict:
        """
        分析患者情况
        
        Returns:
            {
                "risk_level": "low/medium/high",
                "key_concerns": ["关注点1", "关注点2"],
                "search_priorities": [...]
            }
        """
        vital_info = ", ".join([
            f"{v.name}={v.value}{v.unit}" 
            for v in summary.vital_signs[:3]
        ]) if summary.vital_signs else "无"
        
        prompt = f"""作为临床分诊专家，请分析以下患者情况：

患者信息：
- 姓名：{summary.patient_name}
- 年龄：{summary.age}岁，{summary.gender}
- 诊断：{', '.join(summary.diagnoses)}
- 用药：{', '.join([m.name for m in summary.medications])}
- 关键指标：{vital_info}

请输出 JSON 格式：
{{
  "risk_level": "low/medium/high",
  "key_concerns": ["关注点1", "关注点2"],
  "search_priorities": [
    {{"source": "guide", "query": "查询文本", "priority": 1}},
    {{"source": "package_insert", "query": "查询文本", "priority": 2}}
  ]
}}

只输出 JSON，不要有其他文字。"""
        
        try:
            response = await self.llm.chat_completion_with_retry(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return json.loads(response)
        except Exception as e:
            print(f"[Triage Error] {e}")
            return {
                "risk_level": "medium",
                "key_concerns": ["常规随访"],
                "search_priorities": []
            }
