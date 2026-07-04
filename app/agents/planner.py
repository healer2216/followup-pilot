"""Multi-Agent: 规划师 Agent"""

import json
from datetime import datetime
from typing import List
from app.models import (
    DischargeSummary, Evidence, FollowUpPlan, 
    FollowUpTask, TimelineDay
)
from app.tools.llm_gateway import LLMGateway


PLANNER_PROMPT = """你是一个专业的临床随访计划制定专家。

## 任务
根据患者出院信息和循证证据，制定个性化的随访计划。

## 输入
1. 患者出院小结
2. 循证证据列表（已按相关性排序）

## 输出要求
生成 JSON 格式的随访计划，包含4个时间节点：
- 出院第1天
- 出院第3天
- 出院第1周
- 出院第2周（门诊复查）

每个节点包含若干任务，任务类型包括：
- medication: 用药指导
- monitoring: 指标监测
- diet: 饮食建议
- activity: 活动建议
- checkup: 症状自查/门诊复查

## JSON 格式
{{
  "timeline": [
    {{
      "day_number": 1,
      "date": "根据出院日期计算的实际日期，格式 YYYY-MM-DD",
      "label": "出院第1天",
      "tasks": [
        {{
          "task_type": "medication",
          "title": "按时服药",
          "description": "具体描述...",
          "evidence_refs": ["证据标题1"],
          "evidence_grades": ["A"]
        }}
      ]
    }}
  ]
}}

## 重要规则
1. 每个任务必须引用相关证据（如果没有则留空数组）
2. 描述要具体可执行（如"每日晨起测量血压"而非"监测血压"）
3. 考虑患者的特殊情况（年龄、共病、异常指标）
4. 只输出 JSON，不要有其他文字
5. evidence_refs 必须使用循证证据中提供的实际标题，禁止使用"证据1""证据2"等占位符

## 患者信息
{patient_info}

## 循证证据
{evidence_context}
"""


class PlannerAgent:
    """规划师 Agent - 融合患者数据 + 证据，生成随访计划"""
    
    def __init__(self, llm_client: LLMGateway):
        self.llm = llm_client
    
    async def generate(
        self, 
        summary: DischargeSummary,
        evidences: List[Evidence],
        context: str
    ) -> FollowUpPlan:
        """生成随访计划"""
        # 构造患者信息摘要
        vital_info = ", ".join([
            f"{v.name}={v.value}{v.unit}({v.status})" 
            for v in summary.vital_signs[:5]
        ]) if summary.vital_signs else "无"
        
        discharge_str = str(summary.discharge_date) if summary.discharge_date else "未知"
        
        patient_info = f"""
- 姓名：{summary.patient_name}
- 年龄：{summary.age}岁，{summary.gender}
- 出院日期：{discharge_str}
- 诊断：{', '.join(summary.diagnoses)}
- 用药：{', '.join([f'{m.name} {m.dosage} {m.frequency}' for m in summary.medications]) or '无'}
- 关键指标：{vital_info}
"""
        
        # 构造 Prompt
        prompt = PLANNER_PROMPT.format(
            patient_info=patient_info,
            evidence_context=context
        )
        
        # 调用 LLM
        try:
            response = await self.llm.chat_completion_with_retry(
                messages=[{"role": "user", "content": prompt}],
                # 不使用 JSON mode，StepFun 在 JSON mode 下字段名容易出错
                temperature=0.3,
                # 不设 max_tokens，StepFun 在 max_tokens 限制下可能返回空内容
            )
            
            # 尝试解析 JSON，先清理可能的 markdown 包裹
            resp_text = response.strip() if isinstance(response, str) else str(response)
            if resp_text.startswith('```'):
                resp_text = resp_text.split('```', 1)[1]
                if resp_text.endswith('```'):
                    resp_text = resp_text[:-3]
                resp_text = resp_text.strip()
            # 提取第一个 JSON 对象
            start_idx = resp_text.find('{')
            end_idx = resp_text.rfind('}')
            if start_idx != -1 and end_idx > start_idx:
                resp_text = resp_text[start_idx:end_idx+1]
            
            plan_data = json.loads(resp_text)
            
            # 转换为 Pydantic 模型
            return self._build_plan(summary, plan_data, evidences)
            
        except Exception as e:
            print(f"[Planner Error] {e}")
            raw = response if isinstance(response, str) else str(response)
            print(f"[Planner] LLM 原始响应 (前300字): {raw[:300]}")
            return self._fallback_plan(summary)
    
    def _build_plan(
        self, 
        summary: DischargeSummary,
        plan_data: dict,
        evidences: List[Evidence]
    ) -> FollowUpPlan:
        """将 LLM 输出转换为 FollowUpPlan 对象"""
        from datetime import date
        
        timeline_days = []
        for day_data in plan_data.get("timeline", []):
            tasks = []
            for task_data in day_data.get("tasks", []):
                task = FollowUpTask(
                    task_type=task_data["task_type"],
                    title=task_data["title"],
                    description=task_data["description"],
                    evidence_refs=task_data.get("evidence_refs", []),
                    evidence_grades=task_data.get("evidence_grades", []),
                )
                tasks.append(task)
            
            day = TimelineDay(
                day_number=day_data["day_number"],
                date=day_data["date"],
                label=day_data["label"],
                tasks=tasks,
            )
            timeline_days.append(day)
        
        plan = FollowUpPlan(
            patient_id=f"patient_{summary.patient_name}",
            generated_at=datetime.now(),
            summary=summary,
            timeline=timeline_days,
            evidence_stats={
                "total_searched": len(evidences),
                "cited": len(set([
                    ref for day in timeline_days 
                    for task in day.tasks 
                    for ref in task.evidence_refs
                ])),
            },
        )
        
        return plan
    
    def _fallback_plan(self, summary: DischargeSummary) -> FollowUpPlan:
        """LLM 失败时的降级方案 - 基于患者实际数据生成"""
        from datetime import date, timedelta
        
        discharge_date = summary.discharge_date or date.today()
        
        # 基于患者实际用药生成药物任务
        med_tasks = []
        for m in summary.medications:
            med_tasks.append(FollowUpTask(
                task_type="medication",
                title=f"按时服用 {m.name}",
                description=f"{m.name} {m.dosage or ''}，{m.frequency or '遵医嘱'}，{m.timing or ''}".strip(),
                evidence_refs=[],
                evidence_grades=[],
            ))
        if not med_tasks:
            med_tasks.append(FollowUpTask(
                task_type="medication",
                title="按时服药",
                description="按照出院医嘱按时服用所有药物",
                evidence_refs=[], evidence_grades=[],
            ))
        
        # 基于诊断生成监测任务
        monitor_tasks = []
        for diag in summary.diagnoses[:3]:
            if "糖尿病" in diag:
                monitor_tasks.append(FollowUpTask(
                    task_type="monitoring", title="监测血糖",
                    description="每日晨起测量空腹血糖，餐后2小时测量餐后血糖，记录数值",
                    evidence_refs=[], evidence_grades=[],
                ))
            if "高血压" in diag:
                monitor_tasks.append(FollowUpTask(
                    task_type="monitoring", title="监测血压",
                    description="每日早晚各测量一次血压，记录数值，注意观察血压变化趋势",
                    evidence_refs=[], evidence_grades=[],
                ))
        
        # 基于指标生成复查任务
        checkup_tasks = []
        for v in summary.vital_signs:
            if v.status == "high":
                checkup_tasks.append(FollowUpTask(
                    task_type="checkup", title=f"复查{v.name}",
                    description=f"当前{v.name} {v.value}{v.unit}偏高，建议2周后复查",
                    evidence_refs=[], evidence_grades=[],
                ))
        
        diet_tasks = [FollowUpTask(
            task_type="diet", title="饮食管理",
            description="低盐低脂饮食，多吃蔬菜水果，控制主食摄入量",
            evidence_refs=[], evidence_grades=[],
        )]
        
        timeline = [
            TimelineDay(
                day_number=1,
                date=(discharge_date + timedelta(days=0)).isoformat(),
                label="出院第1天",
                tasks=med_tasks + monitor_tasks[:2],
            ),
            TimelineDay(
                day_number=3,
                date=(discharge_date + timedelta(days=2)).isoformat(),
                label="出院第3天",
                tasks=monitor_tasks + diet_tasks,
            ),
            TimelineDay(
                day_number=7,
                date=(discharge_date + timedelta(days=6)).isoformat(),
                label="出院第1周",
                tasks=[FollowUpTask(
                    task_type="checkup", title="一周自我评估",
                    description="回顾一周用药和监测情况，记录不适症状，评估是否需要调整方案",
                    evidence_refs=[], evidence_grades=[],
                )] + monitor_tasks[:1],
            ),
            TimelineDay(
                day_number=14,
                date=(discharge_date + timedelta(days=13)).isoformat(),
                label="出院第2周（门诊复查）",
                tasks=checkup_tasks + [FollowUpTask(
                    task_type="checkup", title="门诊复查",
                    description=f"携带近两周监测记录到门诊复查，诊断：{'、'.join(summary.diagnoses[:3])}",
                    evidence_refs=[], evidence_grades=[],
                )],
            ),
        ]
        
        return FollowUpPlan(
            patient_id=f"patient_{summary.patient_name}",
            generated_at=datetime.now(),
            summary=summary,
            timeline=timeline,
            evidence_stats={"total_searched": 0, "cited": 0},
        )
