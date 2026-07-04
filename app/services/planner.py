"""M3: 随访计划生成服务"""

import json
from datetime import datetime
from app.models import (
    DischargeSummary, Evidence, EvidenceRef, FollowUpPlan, 
    FollowUpTask, TimelineDay, TaskType
)
from app.tools.llm_gateway import LLMGateway


PLANNER_SYSTEM_PROMPT = """你是一个专业的临床随访计划制定助手。
你需要根据患者的出院信息和循证证据，制定个性化的随访计划。

## 输入
1. 患者出院小结（结构化 JSON）
2. 循证证据列表（来自医学指南、论文、药品说明书）

## 输出要求
生成 JSON 格式的随访计划，包含时间线（出院后第1天、第3天、第1周、第2周、第1月）。

每个时间节点包含若干任务，每个任务必须：
- 标注类型（medication/monitoring/appointment/diet/exercise/symptom_check）
- 给出具体可执行的描述
- 引用循证证据（如果有相关证据）

## JSON 格式
{
  "timeline": [
    {
      "day": 1,
      "label": "出院第1天",
      "tasks": [
        {
          "type": "medication",
          "title": "任务标题",
          "detail": "具体描述",
          "target": "目标值（如有）",
          "evidence": {
            "source": "guide",
            "title": "引用的证据标题",
            "snippet": "证据中的关键原文",
            "evidence_id": "证据ID"
          }
        }
      ]
    }
  ]
}

## 规则
1. 优先使用循证证据，无证据时基于临床常识但要标注
2. 任务描述要通俗易懂，患者能直接执行
3. 药物类任务必须引用说明书
4. 复查类任务必须引用指南
5. 每个时间节点 2-4 个任务，不要过多
6. target 字段用于可量化的指标（如血糖范围、血压范围）
"""


class PlannerService:
    """随访计划生成服务"""

    def __init__(self, llm_client: LLMGateway):
        self.llm = llm_client

    async def generate(
        self,
        summary: DischargeSummary,
        evidences: list[Evidence],
    ) -> FollowUpPlan:
        """
        融合患者数据 + 循证证据 → 生成随访计划。
        """
        # 构造 prompt
        evidence_text = self._format_evidences(evidences)
        user_content = (
            f"## 患者出院小结\n{summary.model_dump_json(indent=2)}\n\n"
            f"## 循证证据\n{evidence_text}"
        )

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = await self.llm.chat_completion(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        raw = json.loads(response["content"])
        timeline = [TimelineDay(**day) for day in raw.get("timeline", [])]

        # 统计引用数
        cited_ids = set()
        for day in timeline:
            for task in day.tasks:
                if task.evidence and task.evidence.evidence_id:
                    cited_ids.add(task.evidence.evidence_id)

        plan = FollowUpPlan(
            plan_id=f"plan_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            diagnosis_summary=summary.diagnosis,
            timeline=timeline,
            evidence_pool=evidences,
            evidence_count=len(evidences),
            cited_count=len(cited_ids),
        )

        return plan

    def _format_evidences(self, evidences: list[Evidence]) -> str:
        """将证据列表格式化为 LLM 可读的文本"""
        lines = []
        for i, ev in enumerate(evidences, 1):
            lines.append(
                f"[{i}] ID:{ev.id} | 来源:{ev.source.value} | "
                f"标题:{ev.title}\n"
                f"    摘要:{(ev.abstract or '无')[:200]}"
            )
        return "\n".join(lines)
