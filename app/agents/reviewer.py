"""Multi-Agent: 审核员 Agent"""

import json
from app.models import FollowUpPlan, ReviewVerdict
from app.tools.llm_gateway import LLMGateway


REVIEWER_PROMPT = """你是一个严格的临床随访计划审核专家。

## 任务
评估以下随访计划的质量，给出6维度评分和总体结论。

## 评分维度（每项0-10分）
1. **完整性**: 是否覆盖了用药、监测、饮食、活动、复查等关键方面？
2. **准确性**: 医学建议是否符合循证证据？
3. **可行性**: 任务是否具体可执行？患者能否理解？
4. **个性化**: 是否考虑了患者的特殊情况（年龄、共病、异常指标）？
5. **安全性**: 是否有遗漏的危险信号或预警？
6. **证据支持**: 是否充分引用了相关证据？

## 输入
患者出院小结：
{patient_info}

随访计划：
{plan_json}

## 输出 JSON 格式
{{
  "scores": {{
    "completeness": 8,
    "accuracy": 9,
    "feasibility": 7,
    "personalization": 8,
    "safety": 9,
    "evidence_support": 7
  }},
  "average_score": 8.0,
  "verdict": "approved/needs_revision/rejected",
  "comments": "审核意见..."
}}

只输出 JSON，不要有其他文字。
"""


class ReviewerAgent:
    """审核员 Agent - 6维度评分审核随访计划质量"""
    
    def __init__(self, llm_client: LLMGateway):
        self.llm = llm_client
    
    async def review(self, plan: FollowUpPlan) -> dict:
        """审核随访计划（规则审核，无需 LLM 调用，速度极快）"""
        scores = {}
        
        # 1. 完整性：是否有多个时间节点
        timeline_count = len(plan.timeline)
        scores["completeness"] = min(10.0, timeline_count * 2.5)
        
        # 2. 个性化：任务是否包含患者诊断/用药相关内容
        diag_keywords = [d for d in plan.summary.diagnoses]
        med_names = [m.name for m in plan.summary.medications]
        all_text = " ".join([
            task.title + " " + task.description
            for day in plan.timeline for task in day.tasks
        ])
        
        personalization_hits = sum(
            1 for kw in diag_keywords + med_names if kw and kw in all_text
        )
        scores["personalization"] = min(10.0, personalization_hits * 2.0 + 4.0)
        
        # 3. 可操作性：任务描述是否足够具体
        avg_desc_len = sum(
            len(task.description)
            for day in plan.timeline for task in day.tasks
        ) / max(1, sum(len(day.tasks) for day in plan.timeline))
        scores["actionability"] = min(10.0, avg_desc_len / 15.0 + 3.0)
        
        # 4. 循证支撑：是否有证据引用
        total_refs = sum(
            len(task.evidence_refs)
            for day in plan.timeline for task in day.tasks
        )
        scores["evidence_based"] = min(10.0, total_refs * 1.5 + 3.0)
        
        # 5. 安全性：是否包含异常警示
        safety_keywords = ["就医", "立即", "异常", "不适", "紧急", "门诊"]
        safety_hits = sum(1 for kw in safety_keywords if kw in all_text)
        scores["safety"] = min(10.0, safety_hits * 2.0 + 3.0)
        
        # 6. 可读性：任务数量是否合理
        total_tasks = sum(len(day.tasks) for day in plan.timeline)
        if 8 <= total_tasks <= 25:
            scores["readability"] = 9.0
        elif total_tasks < 8:
            scores["readability"] = 6.0
        else:
            scores["readability"] = 7.0
        
        avg_score = sum(scores.values()) / len(scores)
        verdict = "approved" if avg_score >= 6.0 else "pending"
        
        return {
            "scores": scores,
            "average_score": round(avg_score, 2),
            "verdict": verdict,
            "review_mode": "rule_based",
        }
