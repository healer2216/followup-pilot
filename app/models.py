"""
FollowUp Pilot - 全局数据模型
按技术设计书 2.1 节定义
"""
from __future__ import annotations
from datetime import datetime, date
from enum import Enum
from typing import Any, Optional, List
from pydantic import BaseModel, Field


# ============================================================================
# 枚举类型
# ============================================================================

class EvidenceSource(str, Enum):
    """KnowS 支持的 6 类证据源"""
    PAPER_EN = "paper_en"       # 英文论文
    PAPER_CN = "paper_cn"       # 中文论文
    MEETING = "meeting"         # 会议摘要
    GUIDE = "guide"             # 临床指南
    TRIAL = "trial"             # 临床试验
    PACKAGE_INSERT = "package_insert"  # 药品说明书


class AlertLevel(str, Enum):
    """预警等级"""
    GREEN = "green"   # 正常
    YELLOW = "yellow" # 需要关注
    RED = "red"       # 紧急处理


class TaskType(str, Enum):
    """任务类型"""
    MEDICATION = "medication"
    MONITORING = "monitoring"
    DIET = "diet"
    ACTIVITY = "activity"
    CHECKUP = "checkup"


class TrendDirection(str, Enum):
    """趋势方向"""
    IMPROVING = "improving"     # 持续改善
    STABLE = "stable"           # 稳定
    WORSENING = "worsening"     # 持续恶化
    FLUCTUATING = "fluctuating" # 波动中
    INSUFFICIENT = "insufficient" # 数据不足


class IntentType(str, Enum):
    """对话意图类型"""
    REPORT = "report"      # 指标汇报
    ASK = "ask"            # 咨询问题
    EMERGENCY = "emergency" # 紧急情况
    CHITCHAT = "chitchat"  # 闲聊


class ReviewVerdict(str, Enum):
    """审核结论"""
    APPROVED = "approved"      # 通过
    NEEDS_REVISION = "needs_revision"  # 需要修改
    REJECTED = "rejected"      # 拒绝


# ============================================================================
# 出院小结相关模型
# ============================================================================

class Medication(BaseModel):
    """用药方案"""
    name: str = Field(..., description="药物名称")
    dosage: str = Field(..., description="剂量")
    frequency: str = Field(..., description="频次")
    timing: str = Field("", description="服用时间（如餐后、睡前）")


class VitalSign(BaseModel):
    """检验指标"""
    name: str = Field(..., description="指标名称")
    value: str = Field(..., description="数值（可以是数字或复合值如145/92）")
    unit: str = Field("", description="单位")
    reference_range: str = Field("", description="参考范围")
    status: str = Field("normal", description="状态：normal/high/low")


class DischargeSummary(BaseModel):
    """结构化出院小结"""
    patient_name: str = Field(..., description="患者姓名")
    gender: str = Field(..., description="性别")
    age: int = Field(..., description="年龄")
    
    admission_date: Optional[date] = Field(None, description="入院日期")
    discharge_date: Optional[date] = Field(None, description="出院日期")
    
    diagnoses: List[str] = Field([], description="诊断列表")
    medications: List[Medication] = Field([], description="用药方案")
    vital_signs: List[VitalSign] = Field([], description="检验指标")
    
    chief_complaint: str = Field("", description="主诉")
    treatment_summary: str = Field("", description="治疗经过")
    discharge_instructions: str = Field("", description="出院医嘱")
    
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="解析置信度")
    
    # Validators to handle empty strings as None for optional date fields
    from pydantic import field_validator
    
    @field_validator('admission_date', 'discharge_date', mode='before')
    @classmethod
    def convert_empty_to_none(cls, v):
        if v == '' or v is None:
            return None
        return v


# ============================================================================
# 循证检索相关模型
# ============================================================================

class Evidence(BaseModel):
    """单条证据"""
    source: EvidenceSource = Field(..., description="证据来源")
    title: str = Field(..., description="标题")
    abstract: str = Field("", description="摘要")
    url: str = Field("", description="链接")
    publish_year: int = Field(0, description="发表年份")
    
    grade: str = Field("E", description="证据分级 A-E")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="置信度")


class EvidenceRef(BaseModel):
    """证据引用（轻量版）"""
    source: str = Field(..., description="证据来源")
    title: str = Field(..., description="标题")
    snippet: str = Field("", description="关键片段")
    evidence_id: str = Field("", description="证据ID")
    
    relevance_score: float = Field(0.0, description="相关性得分")
    rerank_score: float = Field(0.0, description="重排序得分")


class SearchQuery(BaseModel):
    """检索查询"""
    query_text: str = Field(..., description="查询文本")
    source: EvidenceSource = Field(..., description="目标数据源")
    question_id: str = Field("", description="问题ID（KnowS返回）")


class SearchResult(BaseModel):
    """检索结果"""
    query: SearchQuery = Field(..., description="原始查询")
    evidences: List[Evidence] = Field([], description="证据列表")
    total_count: int = Field(0, description="总数量")


# ============================================================================
# 随访计划相关模型
# ============================================================================

class FollowUpTask(BaseModel):
    """随访任务"""
    task_type: str = Field(..., description="任务类型：medication/monitoring/diet/activity/checkup")
    title: str = Field(..., description="任务标题")
    description: str = Field(..., description="详细描述")
    icon: str = Field("check-circle", description="图标名称")
    color: str = Field("blue", description="颜色主题")
    
    evidence_refs: List[str] = Field([], description="引用的证据标题列表")
    evidence_grades: List[str] = Field([], description="对应证据分级")


class TimelineDay(BaseModel):
    """时间线节点"""
    day_number: int = Field(..., description="第几天")
    date: str = Field(..., description="具体日期 YYYY-MM-DD")
    label: str = Field("", description="展示标签，如'出院第1天'")
    icon: str = Field("calendar", description="图标名称")
    color: str = Field("medical", description="颜色主题")
    tasks: List[FollowUpTask] = Field([], description="当天任务列表")


class FollowUpPlan(BaseModel):
    """完整随访计划"""
    patient_id: str = Field(..., description="患者ID")
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")
    
    summary: DischargeSummary = Field(..., description="出院小结")
    timeline: List[TimelineDay] = Field([], description="时间线")
    
    evidence_stats: dict = Field({}, description="证据统计：{total_searched, cited, by_grade}")
    risk_profile: dict = Field({}, description="风险画像")
    
    review_verdict: Optional[ReviewVerdict] = Field(None, description="审核结论")
    review_scores: dict = Field({}, description="审核评分")


# ============================================================================
# 患者画像相关模型
# ============================================================================

class RiskProfile(BaseModel):
    """患者风险画像"""
    overall_risk: str = Field("medium", description="整体风险：low/medium/high")
    risk_factors: List[str] = Field([], description="风险因素列表")
    
    special_attention: List[str] = Field([], description="特殊注意事项")
    drug_interactions: List[str] = Field([], description="药物相互作用警告")
    
    personalized_queries: List[str] = Field([], description="个性化查询建议")


# ============================================================================
# 对话随访相关模型
# ============================================================================

class ChatMessage(BaseModel):
    """对话消息"""
    role: str = Field(..., description="角色：user/assistant/system")
    content: str = Field(..., description="消息内容")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    
    alert_level: Optional[AlertLevel] = Field(None, description="预警等级")
    trend_info: Optional[dict] = Field(None, description="趋势信息")
    evidence_refs: List[str] = Field([], description="引用证据")


class ChatSession(BaseModel):
    """会话上下文"""
    session_id: str = Field(..., description="会话ID")
    patient_id: str = Field(..., description="患者ID")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    
    discharge_summary: Optional[DischargeSummary] = Field(None, description="出院小结")
    plan: Optional[FollowUpPlan] = Field(None, description="关联的随访计划")
    messages: List[ChatMessage] = Field([], description="历史消息")
    
    current_alert: AlertLevel = Field(AlertLevel.GREEN, description="当前预警等级")
    vital_records: List[dict] = Field([], description="指标记录 [{date, type, value}]")


class ChatRequest(BaseModel):
    """对话请求"""
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="用户消息")


class ChatResponse(BaseModel):
    """对话响应"""
    reply: str = Field(..., description="AI回复")
    alert_level: AlertLevel = Field(..., description="预警等级")
    trend_direction: Optional[TrendDirection] = Field(None, description="趋势方向")
    evidence_refs: List[str] = Field([], description="引用证据")
    intent: IntentType = Field(..., description="识别的意图")


# ============================================================================
# API 响应包装
# ============================================================================

class ApiResponse(BaseModel):
    """统一API响应"""
    success: bool = Field(..., description="是否成功")
    data: Optional[Any] = Field(None, description="响应数据")
    error: Optional[str] = Field(None, description="错误信息")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
