"""
LangGraph 状态机编排 — 对话随访引擎

架构图：
    START → intent_router
                ├─ emergency → emergency_handler → guardrail → END
                ├─ report → value_extractor → trend_analyzer → evidence_searcher → response_generator → guardrail → END
                ├─ ask → evidence_searcher → response_generator → guardrail → END
                └─ chitchat → response_generator → guardrail → END

    guardrail 条件边：
        ├─ blocked → escalation_handler → END
        └─ passed → END

    trend_analyzer 条件边：
        ├─ upgrade_detected → 提升预警等级
        └─ normal → 继续
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Optional, Any, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.models import (
    ChatSession, ChatMessage, AlertLevel, IntentType, TrendDirection,
    DischargeSummary, Evidence
)
from app.tools.llm_gateway import LLMGateway
from app.services.evidence import EvidenceService
from app.services.trend_analyzer import TrendAnalyzer
from app.services.safety_guardrail import SafetyGuardrail


# ============================================================================
# LangGraph State（TypedDict 风格，兼容 LangGraph）
# ============================================================================

class ChatState(TypedDict):
    """
    LangGraph 对话状态

    字段说明：
    - messages: 对话历史列表
    - session: 会话对象（含出院小结、指标记录等）
    - user_message: 用户当前消息
    - intent: 识别的意图类型
    - extracted_values: 从消息中提取的指标值
    - alert_level: 当前预警等级
    - alert_detail: 预警详情
    - trend_results: 趋势分析结果
    - trend_summary: 趋势摘要
    - extra_evidences: 补充检索的证据
    - reply: AI 生成的回复
    - guardrail_result: 安全护栏检查结果
    - needs_escalation: 是否需要升级处理
    - error: 错误信息
    """
    messages: Annotated[list, add_messages]
    session: Any  # ChatSession
    user_message: str
    intent: Optional[str]
    extracted_values: dict
    alert_level: str
    alert_detail: Optional[str]
    trend_results: Optional[list]
    trend_summary: Optional[dict]
    extra_evidences: list
    reply: Optional[str]
    guardrail_result: Optional[dict]
    needs_escalation: bool
    error: Optional[str]


def make_initial_state(session: ChatSession, user_message: str) -> ChatState:
    """创建初始状态"""
    return ChatState(
        messages=[{"role": "user", "content": user_message}],
        session=session,
        user_message=user_message,
        intent=None,
        extracted_values={},
        alert_level=AlertLevel.GREEN.value,
        alert_detail=None,
        trend_results=None,
        trend_summary=None,
        extra_evidences=[],
        reply=None,
        guardrail_result=None,
        needs_escalation=False,
        error=None,
    )


# ============================================================================
# LangGraph 节点函数
# ============================================================================

class LangGraphChatEngine:
    """
    LangGraph 状态机驱动的对话随访引擎

    节点：
    1. intent_router — 意图分类（4 种）
    2. emergency_handler — 紧急处理
    3. value_extractor — 指标提取
    4. trend_analyzer_node — 趋势分析
    5. evidence_searcher — 按需检索
    6. response_generator — LLM 回复生成
    7. guardrail_checker — 安全护栏检查
    8. escalation_handler — 升级处理
    """

    def __init__(
        self,
        llm_client: LLMGateway,
        evidence_service: EvidenceService,
    ):
        self.llm = llm_client
        self.evidence = evidence_service
        self.trend_analyzer = TrendAnalyzer()
        self.safety_guardrail = SafetyGuardrail()
        self.graph = self._build_graph()

    # -----------------------------------------------------------------------
    # 构建图
    # -----------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态机"""
        graph = StateGraph(ChatState)

        # 添加节点
        graph.add_node("intent_router", self._node_intent_router)
        graph.add_node("emergency_handler", self._node_emergency_handler)
        graph.add_node("value_extractor", self._node_value_extractor)
        graph.add_node("trend_analyzer_node", self._node_trend_analyzer)
        graph.add_node("evidence_searcher", self._node_evidence_searcher)
        graph.add_node("response_generator", self._node_response_generator)
        graph.add_node("guardrail_checker", self._node_guardrail_checker)
        graph.add_node("escalation_handler", self._node_escalation_handler)

        # START → intent_router
        graph.set_entry_point("intent_router")

        # intent_router 条件路由
        graph.add_conditional_edges(
            "intent_router",
            self._route_by_intent,
            {
                "emergency": "emergency_handler",
                "report": "value_extractor",
                "ask": "evidence_searcher",
                "chitchat": "response_generator",
            },
        )

        # emergency_handler → guardrail
        graph.add_edge("emergency_handler", "guardrail_checker")

        # value_extractor → trend_analyzer
        graph.add_edge("value_extractor", "trend_analyzer_node")

        # trend_analyzer → evidence_searcher
        graph.add_edge("trend_analyzer_node", "evidence_searcher")

        # evidence_searcher → response_generator
        graph.add_edge("evidence_searcher", "response_generator")

        # response_generator → guardrail
        graph.add_edge("response_generator", "guardrail_checker")

        # guardrail 条件路由
        graph.add_conditional_edges(
            "guardrail_checker",
            self._route_by_guardrail,
            {
                "blocked": "escalation_handler",
                "passed": END,
            },
        )

        # escalation_handler → END
        graph.add_edge("escalation_handler", END)

        return graph.compile()

    # -----------------------------------------------------------------------
    # 条件路由函数
    # -----------------------------------------------------------------------

    @staticmethod
    def _route_by_intent(state: ChatState) -> str:
        """根据意图路由到不同节点"""
        intent = state.get("intent", "chitchat")
        return intent

    @staticmethod
    def _route_by_guardrail(state: ChatState) -> str:
        """根据护栏结果路由"""
        gr = state.get("guardrail_result")
        if gr and isinstance(gr, dict) and gr.get("blocked"):
            return "blocked"
        return "passed"

    # -----------------------------------------------------------------------
    # 节点实现
    # -----------------------------------------------------------------------

    async def _node_intent_router(self, state: ChatState) -> dict:
        """节点 1: 意图分类"""
        user_msg = state.get("user_message", "")

        # 快速关键词匹配（无需 LLM）
        emergency_keywords = [
            "胸痛", "呼吸困难", "昏迷", "意识模糊", "大量出血",
            "剧烈头痛", "抽搐", "休克", "120", "急诊",
        ]
        if any(kw in user_msg for kw in emergency_keywords):
            return {"intent": IntentType.EMERGENCY.value}

        report_keywords = [
            "血糖", "血压", "体温", "心率", "体重",
            "指标", "测量", "测了", "今天", "空腹", "餐后",
        ]
        if any(kw in user_msg for kw in report_keywords):
            return {"intent": IntentType.REPORT.value}

        ask_keywords = [
            "怎么", "为什么", "能不能", "可以吗", "需要",
            "饮食", "运动", "吃药", "副作用", "不舒服",
        ]
        if any(kw in user_msg for kw in ask_keywords):
            return {"intent": IntentType.ASK.value}

        return {"intent": IntentType.CHITCHAT.value}

    async def _node_emergency_handler(self, state: ChatState) -> dict:
        """节点 2: 紧急处理"""
        return {
            "alert_level": AlertLevel.RED.value,
            "alert_detail": "检测到紧急症状关键词，建议立即就医",
            "reply": (
                " **紧急提醒**\n\n"
                "根据您的描述，可能存在需要紧急处理的情况。\n\n"
                "**请立即采取以下行动：**\n"
                "1. 拨打 120 急救电话，或立即前往最近的急诊科\n"
                "2. 保持安静，避免剧烈活动\n"
                "3. 如有家属在旁，请告知您的症状和用药情况\n\n"
                "---\n"
                "*此提醒基于症状关键词自动触发，不替代医生诊断。*"
            ),
        }

    async def _node_value_extractor(self, state: ChatState) -> dict:
        """节点 3: 指标提取"""
        user_msg = state.get("user_message", "")
        session: ChatSession = state.get("session")

        prompt = f"""从以下患者消息中提取医学指标数值，返回 JSON：
{{"fasting_glucose": 数值或null, "postprandial_glucose": 数值或null,
  "blood_pressure_systolic": 数值或null, "blood_pressure_diastolic": 数值或null,
  "heart_rate": 数值或null, "temperature": 数值或null, "weight": 数值或null}}

只提取明确提到的数值，未提到的填 null。

患者消息："{user_msg}"
"""
        try:
            resp = await self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            raw = json.loads(resp) if isinstance(resp, str) else resp
            values = {k: v for k, v in raw.items() if v is not None}
        except Exception as e:
            print(f"[LangGraph ValueExtract Error] {e}")
            values = {}

        # 记录到 vital_records
        updates: dict = {"extracted_values": values}
        if values and session:
            today_str = date.today().isoformat()
            record = {"date": today_str, **values}
            session.vital_records = [
                r for r in session.vital_records if r.get("date") != today_str
            ]
            session.vital_records.append(record)

        return updates

    async def _node_trend_analyzer(self, state: ChatState) -> dict:
        """节点 4: 趋势分析"""
        session: ChatSession = state.get("session")
        if not session or len(session.vital_records) < 2:
            return {
                "trend_results": None,
                "trend_summary": {"summary": "数据不足，暂无趋势分析", "upgrade_count": 0},
            }

        results = self.trend_analyzer.analyze(session.vital_records)
        summary = self.trend_analyzer.get_summary(results)

        # 趋势升级
        alert_level = state.get("alert_level", AlertLevel.GREEN.value)
        alert_detail = state.get("alert_detail")
        if summary.get("upgrade_count", 0) > 0 and alert_level == AlertLevel.GREEN.value:
            alert_level = AlertLevel.YELLOW.value
            alert_detail = (alert_detail or "") + "；趋势分析发现指标异常变化"

        return {
            "trend_results": [r.to_dict() for r in results],
            "trend_summary": summary,
            "alert_level": alert_level,
            "alert_detail": alert_detail,
        }

    async def _node_evidence_searcher(self, state: ChatState) -> dict:
        """节点 5: 按需检索证据"""
        user_msg = state.get("user_message", "")
        intent = state.get("intent", "chitchat")

        # 仅在 ask/report 意图下检索
        if intent not in (IntentType.ASK.value, IntentType.REPORT.value):
            return {"extra_evidences": []}

        search_triggers = [
            "不舒服", "疼痛", "头晕", "恶心", "失眠",
            "副作用", "过敏", "饮食", "能吃什么",
        ]
        needs_search = any(t in user_msg for t in search_triggers) or intent == IntentType.ASK.value

        if not needs_search:
            return {"extra_evidences": []}

        try:
            evidences = await self.evidence.search_on_demand(user_msg)
            return {"extra_evidences": evidences}
        except Exception as e:
            print(f"[LangGraph EvidenceSearch Error] {e}")
            return {"extra_evidences": []}

    async def _node_response_generator(self, state: ChatState) -> dict:
        """节点 6: LLM 回复生成"""
        session: ChatSession = state.get("session")
        user_msg = state.get("user_message", "")
        alert_level = state.get("alert_level", AlertLevel.GREEN.value)
        values = state.get("extracted_values", {})
        trend_summary = state.get("trend_summary", {})
        extra_evidences = state.get("extra_evidences", [])

        # 构造系统提示
        system_prompt = self._build_system_prompt(session, alert_level)

        # 构造上下文
        context_parts = []
        if extra_evidences:
            context_parts.append("## 相关循证证据")
            for i, ev in enumerate(extra_evidences[:3], 1):
                context_parts.append(f"[{i}] {ev.title}: {(ev.abstract or '')[:150]}")

        if values:
            context_parts.append("## 本次提取的指标")
            context_parts.append(str(values))

        if trend_summary and trend_summary.get("summary"):
            context_parts.append(trend_summary["summary"])

        if alert_level != AlertLevel.GREEN.value:
            context_parts.append(f"\n⚠️ 预警等级: {alert_level.upper()}")

        context = "\n".join(context_parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context + "\n\n患者说：" + user_msg},
        ]

        try:
            response = await self.llm.chat_completion(messages=messages, temperature=0.5)
            reply = response if isinstance(response, str) else response.get("content", "")
        except Exception as e:
            print(f"[LangGraph ResponseGen Error] {e}")
            reply = "抱歉，系统暂时无法生成回复，请稍后再试。"

        return {"reply": reply}

    async def _node_guardrail_checker(self, state: ChatState) -> dict:
        """节点 7: 安全护栏检查"""
        session: ChatSession = state.get("session")
        user_msg = state.get("user_message", "")
        reply = state.get("reply", "")
        alert_level_str = state.get("alert_level", AlertLevel.GREEN.value)
        alert_level = AlertLevel(alert_level_str) if alert_level_str in AlertLevel.__members__.values() else AlertLevel.GREEN

        patient_age = session.discharge_summary.age if session and session.discharge_summary else 65

        result = self.safety_guardrail.check(
            discharge_summary=session.discharge_summary if session else None,
            user_message=user_msg,
            ai_reply=reply,
            alert_level=alert_level,
            patient_age=patient_age,
        )

        updates: dict = {"guardrail_result": result.to_dict()}

        # 如果护栏拦截，修改回复
        if result.blocked:
            safe_reply = reply + "\n\n---\n⚠️ *安全提示：您的情况需要主管医生评估，请联系医生或前往门诊。*"
            updates["reply"] = safe_reply
            updates["needs_escalation"] = True

        return updates

    async def _node_escalation_handler(self, state: ChatState) -> dict:
        """节点 8: 升级处理"""
        reply = state.get("reply", "")
        gr = state.get("guardrail_result", {})
        block_reason = gr.get("block_reason", "安全护栏触发")

        # 追加升级提示
        escalated_reply = reply + (
            f"\n\n---\n"
            f"🚨 **安全升级提示**\n\n"
            f"系统检测到以下安全问题：{block_reason}\n\n"
            f"**建议您：**\n"
            f"1. 立即联系您的主管医生\n"
            f"2. 不要自行调整药物剂量\n"
            f"3. 如症状加重，请前往急诊\n\n"
            f"*本系统仅供健康参考，不替代专业医疗建议。*"
        )

        return {"reply": escalated_reply, "needs_escalation": True}

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    def _build_system_prompt(self, session: ChatSession, alert_level: str) -> str:
        """构造系统提示词"""
        if session and session.discharge_summary:
            ds = session.discharge_summary
            diagnoses = ", ".join(ds.diagnoses) if ds.diagnoses else "未知"
            medications = ", ".join([m.name for m in ds.medications])
        else:
            diagnoses = "未知"
            medications = ""

        prompt = f"""你是一个专业且温暖的 AI 随访护士。
你的任务是根据患者的随访计划，评估他们的恢复情况。

## 患者信息
- 诊断：{diagnoses}
- 当前用药：{medications}

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

        if alert_level == AlertLevel.RED.value:
            prompt += "\n\n⚠️ **当前为红色预警状态**，请务必建议患者立即就医！"
        elif alert_level == AlertLevel.YELLOW.value:
            prompt += "\n\n⚠️ **当前为黄色关注状态**，请给予调整建议并持续监测。"

        return prompt

    # -----------------------------------------------------------------------
    # 入口方法
    # -----------------------------------------------------------------------

    async def chat(self, session: ChatSession, user_message: str) -> dict:
        """
        LangGraph 状态机入口

        执行完整流程并返回结果
        """
        initial_state = make_initial_state(session, user_message)

        # 执行图
        final_state = await self.graph.ainvoke(initial_state)

        # 提取结果
        reply = final_state.get("reply", "")
        alert_level = final_state.get("alert_level", AlertLevel.GREEN.value)
        alert_detail = final_state.get("alert_detail")
        trend_summary = final_state.get("trend_summary")
        trend_results = final_state.get("trend_results")
        guardrail_result = final_state.get("guardrail_result")
        extra_evidences = final_state.get("extra_evidences", [])

        # 更新会话
        evidence_ref_strings = [
            f"{ev.source.value if isinstance(ev.source, Evidence) else ev.source}: {ev.title}"
            for ev in (extra_evidences or [])[:3]
        ]

        trend_info = None
        if trend_results:
            trend_info = {
                "direction": trend_summary.get("summary", "") if trend_summary else "",
                "upgrades": [r for r in trend_results if r.get("upgrade_alert")],
            }

        user_msg = ChatMessage(role="user", content=user_message)
        assistant_msg = ChatMessage(
            role="assistant",
            content=reply,
            alert_level=AlertLevel(alert_level),
            trend_info=trend_info,
            evidence_refs=evidence_ref_strings,
        )
        session.messages.extend([user_msg, assistant_msg])
        session.current_alert = AlertLevel(alert_level)

        return {
            "reply": reply,
            "alert_level": alert_level,
            "alert_detail": alert_detail,
            "evidence_refs": [{"text": ref} for ref in evidence_ref_strings],
            "suggest_actions": self._generate_actions(alert_level),
            "vital_records": session.vital_records,
            "trend_analysis": {
                "summary": trend_summary.get("summary", "数据不足") if trend_summary else "数据不足",
                "upgrade_count": trend_summary.get("upgrade_count", 0) if trend_summary else 0,
                "details": trend_results or [],
            } if trend_results else None,
            "safety_guardrail": guardrail_result,
            "intent": final_state.get("intent", "chitchat"),
        }

    @staticmethod
    def _generate_actions(alert_level: str) -> list[str]:
        """根据预警等级生成建议行动"""
        if alert_level == AlertLevel.RED.value:
            return ["立即联系医生或前往急诊", "记录当前症状和指标"]
        elif alert_level == AlertLevel.YELLOW.value:
            return ["继续监测指标变化", "调整饮食和作息", "如症状持续，提前门诊复查"]
        return ["继续保持当前方案", "按时服药和复查"]
