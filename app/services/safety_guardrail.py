"""
四层安全护栏引擎

四层防护（逐层检查，层层拦截）：
  Layer 1: 药物安全检查（相互作用、剂量合理性、禁忌症）
  Layer 2: 诊断安全检查（诊断-症状一致性、遗漏风险）
  Layer 3: 矛盾检测（患者陈述与医嘱矛盾、指标与症状矛盾）
  Layer 4: 合规审查（禁止剂量建议、免责声明、紧急升级）
"""

from __future__ import annotations
from typing import Optional
from app.models import DischargeSummary, AlertLevel, Medication


# ============================================================================
# 药物相互作用数据库（常见高危组合）
# ============================================================================

DRUG_INTERACTIONS = [
    {
        "drugs": ["华法林", "阿司匹林"],
        "severity": "high",
        "description": "华法林 + 阿司匹林联用显著增加出血风险",
        "action": "建议监测凝血功能（INR），注意出血征象",
    },
    {
        "drugs": ["二甲双胍", "造影剂"],
        "severity": "high",
        "description": "二甲双胍与含碘造影剂联用可增加乳酸酸中毒风险",
        "action": "造影检查前后 48 小时停用二甲双胍",
    },
    {
        "drugs": ["ACEI", "螺内酯"],
        "severity": "medium",
        "description": "ACEI + 螺内酯联用可增加高钾血症风险",
        "action": "建议定期监测血钾水平",
    },
    {
        "drugs": ["地高辛", "氨氯地平"],
        "severity": "medium",
        "description": "氨氯地平可能升高地高辛血药浓度",
        "action": "监测地高辛血药浓度，注意中毒症状",
    },
    {
        "drugs": ["磺脲类", "氟康唑"],
        "severity": "high",
        "description": "氟康唑可显著增强磺脲类降糖作用，致低血糖",
        "action": "联用时减少磺脲类剂量，加强血糖监测",
    },
    {
        "drugs": ["他汀类", "红霉素"],
        "severity": "high",
        "description": "红霉素抑制他汀代谢，增加横纹肌溶解风险",
        "action": "避免联用，或换用不经 CYP3A4 代谢的他汀",
    },
    {
        "drugs": ["氯吡格雷", "奥美拉唑"],
        "severity": "medium",
        "description": "奥美拉唑可减弱氯吡格雷抗血小板作用",
        "action": "建议换用泮托拉唑或雷贝拉唑",
    },
]

# 高危药物（老年人需特别注意）
HIGH_RISK_DRUGS_ELDERLY = {
    "格列本脲": "低血糖风险高，老年人建议换用格列美脲",
    "地西泮": "跌倒风险增加，建议换用短效苯二氮䓬类",
    "吲哚美辛": "胃肠道出血风险高，建议换用其他 NSAIDs",
    "阿米替林": "抗胆碱副作用强，老年人不推荐",
}

# 剂量上限（单日最大剂量）
MAX_DAILY_DOSES = {
    "二甲双胍": {"max": 2550, "unit": "mg"},
    "阿托伐他汀": {"max": 80, "unit": "mg"},
    "氨氯地平": {"max": 10, "unit": "mg"},
    "布洛芬": {"max": 2400, "unit": "mg"},
    "对乙酰氨基酚": {"max": 4000, "unit": "mg"},
    "华法林": {"max": 10, "unit": "mg"},
    "地高辛": {"max": 0.5, "unit": "mg"},
}


# ============================================================================
# 护栏检查结果
# ============================================================================

class GuardrailFinding:
    """单条护栏发现"""

    def __init__(self, layer: int, severity: str, category: str, message: str, action: str = ""):
        self.layer = layer          # 1-4
        self.severity = severity    # info / warning / critical
        self.category = category    # 分类标签
        self.message = message      # 描述
        self.action = action        # 建议行动

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "action": self.action,
        }


class GuardrailResult:
    """护栏检查完整结果"""

    def __init__(self):
        self.findings: list[GuardrailFinding] = []
        self.passed = True           # 是否通过所有关键检查
        self.blocked = False         # 是否被拦截（critical 级别）
        self.block_reason = ""

    def add(self, finding: GuardrailFinding):
        self.findings.append(finding)
        if finding.severity == "critical":
            self.passed = False
            self.blocked = True
            self.block_reason = finding.message

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "findings_count": len(self.findings),
            "critical_count": sum(1 for f in self.findings if f.severity == "critical"),
            "warning_count": sum(1 for f in self.findings if f.severity == "warning"),
            "info_count": sum(1 for f in self.findings if f.severity == "info"),
            "findings": [f.to_dict() for f in self.findings],
        }


# ============================================================================
# 四层安全护栏引擎
# ============================================================================

class SafetyGuardrail:
    """
    四层安全护栏

    使用方式：
        guardrail = SafetyGuardrail()
        result = guardrail.check(
            discharge_summary=summary,
            user_message="我觉得头晕，想把二甲双胍停了",
            alert_level=AlertLevel.YELLOW,
        )
    """

    def check(
        self,
        discharge_summary: Optional[DischargeSummary],
        user_message: str = "",
        ai_reply: str = "",
        alert_level: AlertLevel = AlertLevel.GREEN,
        patient_age: int = 65,
    ) -> GuardrailResult:
        """执行四层检查"""
        result = GuardrailResult()

        # Layer 1: 药物安全
        if discharge_summary and discharge_summary.medications:
            self._check_layer1_drug_safety(discharge_summary, patient_age, result)

        # Layer 2: 诊断安全
        if discharge_summary:
            self._check_layer2_diagnostic_safety(discharge_summary, user_message, result)

        # Layer 3: 矛盾检测
        if discharge_summary and user_message:
            self._check_layer3_contradiction(discharge_summary, user_message, result)

        # Layer 4: 合规审查
        self._check_layer4_compliance(ai_reply, alert_level, result)

        return result

    # -----------------------------------------------------------------------
    # Layer 1: 药物安全检查
    # -----------------------------------------------------------------------

    def _check_layer1_drug_safety(self, summary: DischargeSummary, age: int, result: GuardrailResult):
        """检查药物相互作用、剂量合理性、老年人高危药物"""
        med_names = [m.name for m in summary.medications]

        # 1a. 药物相互作用
        for interaction in DRUG_INTERACTIONS:
            drugs = interaction["drugs"]
            matched = [d for d in drugs if any(d in name for name in med_names)]
            if len(matched) >= 2:
                severity = "critical" if interaction["severity"] == "high" else "warning"
                result.add(GuardrailFinding(
                    layer=1,
                    severity=severity,
                    category="药物相互作用",
                    message=f"⚠️ {interaction['description']}",
                    action=interaction["action"],
                ))

        # 1b. 老年人高危药物
        if age >= 65:
            for med in summary.medications:
                for risky_name, warning in HIGH_RISK_DRUGS_ELDERLY.items():
                    if risky_name in med.name:
                        result.add(GuardrailFinding(
                            layer=1,
                            severity="warning",
                            category="老年人用药风险",
                            message=f"患者 ≥65 岁，使用 {risky_name}：{warning}",
                            action=f"建议与主管医生确认是否可替换为更安全的替代药物",
                        ))

        # 1c. 剂量合理性（简单检查）
        for med in summary.medications:
            self._check_dosage(med, result)

    def _check_dosage(self, med: Medication, result: GuardrailResult):
        """简单剂量检查"""
        for drug_name, limit in MAX_DAILY_DOSES.items():
            if drug_name in med.name:
                # 尝试从 dosage 中提取数值
                try:
                    import re
                    numbers = re.findall(r'(\d+(?:\.\d+)?)', med.dosage)
                    if numbers:
                        dose_val = float(numbers[0])
                        if dose_val > limit["max"]:
                            result.add(GuardrailFinding(
                                layer=1,
                                severity="critical",
                                category="剂量超标",
                                message=f"{drug_name} 单次剂量 {dose_val}{limit['unit']} 超过日最大剂量 {limit['max']}{limit['unit']}",
                                action=f"请核实处方剂量，{drug_name} 日最大剂量为 {limit['max']}{limit['unit']}",
                            ))
                except Exception:
                    pass

    # -----------------------------------------------------------------------
    # Layer 2: 诊断安全检查
    # -----------------------------------------------------------------------

    def _check_layer2_diagnostic_safety(self, summary: DischargeSummary, user_message: str, result: GuardrailResult):
        """检查诊断-症状一致性，提示遗漏风险"""
        diagnoses_text = " ".join(summary.diagnoses).lower()

        # 高危诊断需要特别关注
        high_risk_diagnoses = {
            "心肌梗死": "注意监测心电图变化和心肌酶谱",
            "脑卒中": "注意神经功能恢复情况，预防跌倒",
            "肺栓塞": "注意呼吸状况，抗凝治疗依从性",
            "糖尿病酮症": "密切监测血糖和酮体，保证充分补液",
            "恶性心律失常": "定期心电图监测，避免电解质紊乱",
        }

        for diagnosis, attention in high_risk_diagnoses.items():
            if diagnosis in diagnoses_text:
                result.add(GuardrailFinding(
                    layer=2,
                    severity="info",
                    category="诊断安全提示",
                    message=f"高危诊断「{diagnosis}」：{attention}",
                    action="确保随访计划中包含相应监测项目",
                ))

        # 检查是否有重要出院医嘱缺失
        if summary.discharge_instructions:
            important_keywords = ["复查", "随访", "急诊", "紧急", "立即就医"]
            has_followup = any(kw in summary.discharge_instructions for kw in important_keywords)
            if not has_followup:
                result.add(GuardrailFinding(
                    layer=2,
                    severity="info",
                    category="出院医嘱完整性",
                    message="出院医嘱中未明确提及复查/随访时间",
                    action="建议在随访计划中强调首次门诊复查时间",
                ))

    # -----------------------------------------------------------------------
    # Layer 3: 矛盾检测
    # -----------------------------------------------------------------------

    def _check_layer3_contradiction(self, summary: DischargeSummary, user_message: str, result: GuardrailResult):
        """检测患者陈述与医嘱之间的矛盾"""
        meds_text = " ".join([m.name for m in summary.medications]).lower()
        msg = user_message.lower()

        # 3a. 患者想停药
        stop_keywords = ["不想吃", "停药", "不吃了", "停掉", "不用吃"]
        if any(kw in msg for kw in stop_keywords):
            # 检查是否提到具体药物
            mentioned_meds = [m.name for m in summary.medications if m.name.lower() in msg]
            if mentioned_meds:
                result.add(GuardrailFinding(
                    layer=3,
                    severity="warning",
                    category="停药风险",
                    message=f"患者表达停用 {', '.join(mentioned_meds)} 的意愿",
                    action="请解释遵医嘱用药的重要性，不建议自行停药；如确有顾虑，建议与主管医生沟通",
                ))
            else:
                result.add(GuardrailFinding(
                    layer=3,
                    severity="info",
                    category="停药意向",
                    message="患者表达停药意向，需进一步了解原因",
                    action="询问患者停药原因，进行用药教育",
                ))

        # 3b. 患者想加药/自行用药
        add_keywords = ["自己买", "药店买", "加一种", "试试", "朋友推荐", "中药"]
        if any(kw in msg for kw in add_keywords):
            result.add(GuardrailFinding(
                layer=3,
                severity="warning",
                category="自行加药风险",
                message="患者有自行加药的意向，可能存在药物相互作用风险",
                action="告知患者新增任何药物前需咨询医生或药师，避免与当前用药产生相互作用",
            ))

        # 3c. 指标与症状矛盾
        if "正常" in msg and any(w in msg for w in ["不舒服", "难受", "疼", "头晕"]):
            result.add(GuardrailFinding(
                layer=3,
                severity="info",
                category="陈述矛盾",
                message="患者同时报告指标正常和身体不适，需进一步澄清",
                action="详细询问不适的具体表现和持续时间",
            ))

    # -----------------------------------------------------------------------
    # Layer 4: 合规审查（检查 AI 回复本身）
    # -----------------------------------------------------------------------

    def _check_layer4_compliance(self, ai_reply: str, alert_level: AlertLevel, result: GuardrailResult):
        """审查 AI 回复是否符合合规要求"""
        if not ai_reply:
            return

        # 4a. 禁止给出具体剂量调整建议
        dose_suggest_patterns = [
            "建议您将.*减为", "建议您将.*增为", "可以把.*改为",
            "剂量调整为", "减药", "加量", "增量", "停药",
        ]
        import re
        for pattern in dose_suggest_patterns:
            if re.search(pattern, ai_reply):
                result.add(GuardrailFinding(
                    layer=4,
                    severity="critical",
                    category="禁止剂量建议",
                    message="AI 回复中包含具体的药物剂量调整建议，违反安全规范",
                    action="请修改回复，建议患者与主管医生沟通药物调整",
                ))
                break

        # 4b. 红色预警必须有免责声明
        if alert_level == AlertLevel.RED:
            if "仅供参考" not in ai_reply and "不替代" not in ai_reply and "就医" not in ai_reply:
                result.add(GuardrailFinding(
                    layer=4,
                    severity="critical",
                    category="缺少免责声明",
                    message="红色预警状态下 AI 回复缺少免责声明或就医建议",
                    action="请在回复末尾添加免责声明并建议立即就医",
                ))

        # 4c. 紧急升级检查
        if alert_level == AlertLevel.RED:
            emergency_keywords = ["急诊", "立即就医", "120", "急诊科", "紧急"]
            if not any(kw in ai_reply for kw in emergency_keywords):
                result.add(GuardrailFinding(
                    layer=4,
                    severity="warning",
                    category="缺少紧急就医提示",
                    message="红色预警状态下 AI 回复未包含紧急就医建议",
                    action="请在回复中明确建议患者立即就医或拨打 120",
                ))

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    def get_context_for_llm(self, result: GuardrailResult) -> str:
        """生成注入 LLM 上下文的护栏提示"""
        if not result.findings:
            return ""

        lines = ["\n## 安全护栏提示（请务必遵守）"]
        for f in result.findings:
            prefix = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(f.severity, "•")
            lines.append(f"{prefix} [{f.category}] {f.message}")
            if f.action:
                lines.append(f"   → {f.action}")

        if result.blocked:
            lines.append(f"\n🚫 **安全拦截**：{result.block_reason}")
            lines.append("请勿给出具体建议，引导患者联系主管医生。")

        return "\n".join(lines)
