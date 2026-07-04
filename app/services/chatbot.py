"""M4: 对话随访引擎"""

import json
from datetime import date
from app.models import (
    ChatSession, ChatMessage, EvidenceRef, AlertLevel,
    DischargeSummary, FollowUpPlan, Evidence, EvidenceSource
)
from app.tools.llm_gateway import LLMGateway
from app.services.evidence import EvidenceService
from app.services.trend_analyzer import TrendAnalyzer
from app.services.safety_guardrail import SafetyGuardrail


CHATBOT_SYSTEM_PROMPT = """你是一个专业且温暖的 AI 随访护士。
你的任务是根据患者的随访计划，评估他们的恢复情况。

## 患者信息
- 诊断：{diagnosis}
- 当前用药：{medications}
- 随访计划中的关注点：{focus_points}

## 你的行为准则
1. 语气温暖但专业，像一位关心的护士
2. 主动询问关键指标（血糖/血压/症状等）
3. 对患者的回答做出评估：
   - 指标正常 → 肯定并鼓励
   - 轻度异常 → 给出调整建议
   - 严重异常 → 明确建议就医
4. 每次回复都引用循证依据
5. 不要给出具体的药物调整建议（那是医生的职责）
6. 末尾总是问一个后续问题，引导患者继续交流

## 回复格式
请用自然语言回复，在关键建议后用方括号标注循证来源：
[来源：XXX指南/说明书 - 关键原文摘要]

## 免责声明
每次回复末尾附上：
---
*以上建议仅供参考，不替代专业医嘱。如症状加重，请及时就医。*
"""


class AlertEngine:
    """预警规则引擎（独立于 LLM，保证可靠性）"""

    # 红色预警阈值
    RED_THRESHOLDS = {
        "fasting_glucose": {"high": 13.9, "low": 3.9, "unit": "mmol/L"},
        "blood_pressure_systolic": {"high": 180, "unit": "mmHg"},
        "blood_pressure_diastolic": {"high": 110, "unit": "mmHg"},
    }

    # 黄色关注阈值
    YELLOW_THRESHOLDS = {
        "fasting_glucose": {"high": 10.0, "low": 4.4, "unit": "mmol/L"},
        "blood_pressure_systolic": {"high": 140, "unit": "mmHg"},
        "blood_pressure_diastolic": {"high": 90, "unit": "mmHg"},
    }

    # 关键词触发红色预警
    RED_KEYWORDS = [
        "胸痛", "胸闷", "呼吸困难", "意识模糊", "昏迷",
        "大量出血", "剧烈头痛", "抽搐", "过敏性休克"
    ]

    def evaluate(self, message: str, extracted_values: dict) -> tuple[AlertLevel, str]:
        """
        评估消息中的指标值 + 关键词。

        Args:
            message: 患者原始消息
            extracted_values: LLM 从消息中提取的数值 {"fasting_glucose": 6.8, ...}

        Returns:
            (alert_level, alert_detail)
        """
        # 1. 关键词检查（最高优先级）
        for keyword in self.RED_KEYWORDS:
            if keyword in message:
                return AlertLevel.RED, f"检测到危险症状关键词「{keyword}」，建议立即就医"

        # 2. 数值检查
        alert_level = AlertLevel.GREEN
        detail = None

        for key, value in extracted_values.items():
            if not isinstance(value, (int, float)):
                continue

            # 红色阈值
            if key in self.RED_THRESHOLDS:
                t = self.RED_THRESHOLDS[key]
                if value >= t.get("high", float("inf")) or value <= t.get("low", 0):
                    return AlertLevel.RED, f"{key} = {value} {t['unit']}，超出安全范围"

            # 黄色阈值
            if key in self.YELLOW_THRESHOLDS:
                t = self.YELLOW_THRESHOLDS[key]
                if value >= t.get("high", float("inf")) or value <= t.get("low", 0):
                    if alert_level != AlertLevel.RED:
                        alert_level = AlertLevel.YELLOW
                        detail = f"{key} = {value} {t['unit']}，需要关注"

        return alert_level, detail


class ChatbotService:
    """对话随访引擎（含趋势分析 + 四层安全护栏）"""

    def __init__(self, llm_client: LLMGateway, evidence_service: EvidenceService):
        self.llm = llm_client
        self.evidence = evidence_service
        self.alert_engine = AlertEngine()
        self.trend_analyzer = TrendAnalyzer()
        self.safety_guardrail = SafetyGuardrail()

    async def chat(
        self,
        session: ChatSession,
        message: str,
    ) -> dict:
        """
        处理一轮对话。

        流程：
        1. LLM 提取消息中的数值指标
        2. 规则引擎评估预警等级
        3. 如需补充证据 → 调用 KnowS
        4. LLM 生成回复（注入证据 + 预警上下文）
        """
        # Step 1: 提取数值（快速调用，低 token）
        values = await self._extract_values(message, session)

        # Step 1.5: 记录指标到 vital_records（用于趋势分析）
        if values:
            today_str = date.today().isoformat()
            record = {"date": today_str, **values}
            # 避免同一天重复记录（覆盖）
            session.vital_records = [
                r for r in session.vital_records if r.get("date") != today_str
            ]
            session.vital_records.append(record)

        # Step 2: 预警评估
        alert_level, alert_detail = self.alert_engine.evaluate(message, values)

        # Step 2.5: 趋势分析（需要 ≥2 条记录）
        trend_results = []
        trend_summary = {}
        if len(session.vital_records) >= 2:
            trend_results = self.trend_analyzer.analyze(session.vital_records)
            trend_summary = self.trend_analyzer.get_summary(trend_results)
            # 趋势升级：如果有趋势预警，提升 alert_level
            if trend_summary.get("upgrade_count", 0) > 0 and alert_level == AlertLevel.GREEN:
                alert_level = AlertLevel.YELLOW
                alert_detail = (alert_detail or "") + "；趋势分析发现指标异常变化"

        # Step 3: 按需检索（当患者提到新症状时）
        extra_evidences = []
        if self._needs_evidence_search(message):
            extra_evidences = await self.evidence.search_on_demand(message)

        # Step 4: 构造 LLM 上下文（注入趋势信息）并生成回复
        system_prompt = self._build_system_prompt(session, alert_level)
        context = self._build_context(session, extra_evidences, values, alert_level, trend_summary)

        messages = [
            {"role": "system", "content": system_prompt},
            *self._history_to_messages(session.messages[-10:]),  # 最近 10 轮
            {"role": "user", "content": context + "\n\n患者说：" + message},
        ]

        response = await self.llm.chat_completion(
            messages=messages,
            temperature=0.5,
        )

        reply_text = response if isinstance(response, str) else response.get("content", "")

        # Step 4.5: 四层安全护栏检查（检查 AI 回复）
        patient_age = session.discharge_summary.age if session.discharge_summary else 65
        guardrail_result = self.safety_guardrail.check(
            discharge_summary=session.discharge_summary,
            user_message=message,
            ai_reply=reply_text,
            alert_level=alert_level,
            patient_age=patient_age,
        )
        # 如果护栏拦截，追加安全提示到回复末尾
        if guardrail_result.blocked:
            reply_text += "\n\n---\n⚠️ *安全提示：您的情况需要主管医生评估，请联系医生或前往门诊。*"

        # Step 5: 更新会话状态
        user_msg = ChatMessage(role="user", content=message)
        
        evidence_ref_strings = [
            f"{ev.source.value if isinstance(ev.source, EvidenceSource) else ev.source}: {ev.title}"
            for ev in extra_evidences[:3]
        ]
        
        # 趋势信息
        trend_info = None
        if trend_results:
            trend_info = {
                "direction": trend_summary.get("summary", ""),
                "upgrades": [r.to_dict() for r in trend_results if r.upgrade_alert],
            }
        
        assistant_msg = ChatMessage(
            role="assistant",
            content=reply_text,
            alert_level=alert_level,
            trend_info=trend_info,
            evidence_refs=evidence_ref_strings,
        )
        session.messages.extend([user_msg, assistant_msg])
        session.current_alert = alert_level

        return {
            "reply": reply_text,
            "alert_level": alert_level.value,
            "alert_detail": alert_detail,
            "evidence_refs": [
                {"text": ref}
                for ref in assistant_msg.evidence_refs
            ],
            "suggest_actions": self._generate_actions(alert_level, values),
            "vital_records": session.vital_records,
            "trend_analysis": {
                "summary": trend_summary.get("summary", "数据不足，暂无趋势分析"),
                "upgrade_count": trend_summary.get("upgrade_count", 0),
                "details": [r.to_dict() for r in trend_results],
            } if trend_results else None,
            "safety_guardrail": guardrail_result.to_dict() if guardrail_result.findings else None,
        }

    async def _extract_values(self, message: str, session: ChatSession) -> dict:
        """用 LLM 从消息中提取数值指标（轻量调用）"""
        prompt = f"""从以下患者消息中提取医学指标数值，返回 JSON：
{{"fasting_glucose": 数值或null, "postprandial_glucose": 数值或null,
  "blood_pressure_systolic": 数值或null, "blood_pressure_diastolic": 数值或null,
  "heart_rate": 数值或null, "temperature": 数值或null, "weight": 数值或null}}

只提取明确提到的数值，未提到的填 null。

患者消息："{message}"
"""
        try:
            resp = await self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            # chat_completion 返回的是字符串，需要解析 JSON
            raw_json = json.loads(resp) if isinstance(resp, str) else resp
            return {k: v for k, v in raw_json.items() if v is not None}
        except Exception as e:
            print(f"[Extract Values Error] {e}")
            return {}

    def _needs_evidence_search(self, message: str) -> bool:
        """判断是否需要补充检索"""
        search_triggers = [
            "不舒服", "疼痛", "头晕", "恶心", "失眠",
            "副作用", "过敏", "饮食", "能吃什么",
        ]
        return any(trigger in message for trigger in search_triggers)

    def _build_system_prompt(self, session: ChatSession, alert_level: AlertLevel) -> str:
        """构造系统提示词"""
        if session.discharge_summary:
            diagnoses = ", ".join(session.discharge_summary.diagnoses) if session.discharge_summary.diagnoses else "未知"
            medications = ", ".join([m.name for m in session.discharge_summary.medications])
        else:
            diagnoses = "未知"
            medications = ""
        focus_points = "按时服药、监测指标、注意症状变化"

        prompt = CHATBOT_SYSTEM_PROMPT.format(
            diagnosis=diagnoses,
            medications=medications,
            focus_points=focus_points
        )

        if alert_level == AlertLevel.RED:
            prompt += "\n\n⚠️ **当前为红色预警状态**，请务必建议患者立即就医！"
        elif alert_level == AlertLevel.YELLOW:
            prompt += "\n\n⚠️ **当前为黄色关注状态**，请给予调整建议并持续监测。"

        return prompt

    def _build_context(self, session: ChatSession, extra_evidences: list[Evidence], 
                      values: dict, alert_level: AlertLevel,
                      trend_summary: dict = None) -> str:
        """构建对话上下文（含趋势信息）"""
        context_parts = []

        if extra_evidences:
            context_parts.append("## 相关循证证据")
            for i, ev in enumerate(extra_evidences[:3], 1):
                context_parts.append(f"[{i}] {ev.title}: {(ev.abstract or '')[:150]}")

        if values:
            context_parts.append("## 本次提取的指标")
            context_parts.append(str(values))

        # 注入趋势分析
        if trend_summary and trend_summary.get("summary"):
            context_parts.append(trend_summary["summary"])

        if alert_level != AlertLevel.GREEN:
            context_parts.append(f"\n⚠️ 预警等级: {alert_level.value.upper()}")

        return "\n".join(context_parts)

    def _history_to_messages(self, history: list[ChatMessage]) -> list[dict]:
        """转换历史消息为 LLM 格式"""
        return [{"role": msg.role, "content": msg.content} for msg in history]

    def _generate_actions(self, alert_level: AlertLevel, values: dict) -> list[str]:
        """根据预警等级生成建议行动"""
        actions = []
        if alert_level == AlertLevel.RED:
            actions.append("立即联系医生或前往急诊")
            actions.append("记录当前症状和指标")
        elif alert_level == AlertLevel.YELLOW:
            actions.append("继续监测指标变化")
            actions.append("调整饮食和作息")
            actions.append("如症状持续，提前门诊复查")
        else:
            actions.append("继续保持当前方案")
            actions.append("按时服药和复查")
        return actions
