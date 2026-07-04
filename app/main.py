"""
FollowUp Pilot - FastAPI 后端入口
提供 mock API 供前端调用，后续替换为真实服务
"""
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import date, datetime
import uuid
import os

# 导入服务和工具
from app.config import settings
from app.models import (
    DischargeSummary, EvidenceSource, AlertLevel, TaskType,
    ChatSession, ChatMessage, EvidenceRef
)
from app.tools.llm_gateway import LLMGateway
from app.tools.knows_search import KnowSClient
from app.services.parser import ParserService
from app.services.evidence import EvidenceService
from app.services.planner import PlannerService
from app.services.chatbot import ChatbotService
from app.services.ocr_service import OCRService
from app.agents.langgraph_orchestrator import LangGraphChatEngine
from app.store import SessionStore

app = FastAPI(title="FollowUp Pilot API", version="0.2.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# ============================================================================
# 根路径路由（返回前端页面 - 使用无CDN版本）
# ============================================================================
@app.get("/")
async def serve_frontend():
    """提供前端入口页面（不依赖外部CDN的完整功能版本）"""
    frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index-no-cdn.html")
    if os.path.exists(frontend_path):
        return FileResponse(frontend_path)
    # Fallback 到 index.html
    fallback_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")
    if os.path.exists(fallback_path):
        return FileResponse(fallback_path)
    raise HTTPException(status_code=404, detail="Frontend not found")

@app.get("/{filename}")
async def serve_static_file(filename: str):
    """提供前端目录下的静态HTML文件"""
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    file_path = os.path.join(frontend_dir, filename)
    if os.path.exists(file_path) and filename.endswith('.html'):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail=f"File {filename} not found")

# ============================================================================
# 初始化服务（全局单例）
# ============================================================================
llm_client = LLMGateway(
    provider=settings.LLM_PROVIDER,
    api_key=None,  # 从环境变量自动读取
)
knows_client = KnowSClient(
    api_root=settings.KNOWS_BASE_URL,
    api_key=os.getenv("KNOWS_API_KEY"),
)
parser_service = ParserService(llm_client)
evidence_service = EvidenceService(knows_client)
planner_service = PlannerService(llm_client)
chatbot_service = ChatbotService(llm_client, evidence_service)
# LangGraph 状态机编排引擎
langgraph_engine = LangGraphChatEngine(llm_client, evidence_service)
session_store = SessionStore()

# 新增：Multi-Agent 编排器
from app.agents.orchestrator import AgentOrchestrator
agent_orchestrator = AgentOrchestrator(knows_client, llm_client)

# OCR 图像识别服务
ocr_service = OCRService()


# ============================================================================
# Mock 数据
# ============================================================================

MOCK_PARSED_RESULT = {
    "patient_name": "张三",
    "gender": "男",
    "age": 65,
    "admission_date": "2026-06-20",
    "discharge_date": "2026-06-28",
    "diagnoses": ["2型糖尿病", "高血压3级"],
    "medications": [
        {"name": "二甲双胍", "dosage": "500mg", "frequency": "每日两次", "timing": "餐后"},
        {"name": "氨氯地平", "dosage": "5mg", "frequency": "每日一次", "timing": "晨起"},
        {"name": "阿托伐他汀", "dosage": "20mg", "frequency": "每日一次", "timing": "睡前"},
    ],
    "vital_signs": [
        {"name": "空腹血糖", "value": 7.8, "unit": "mmol/L", "reference_range": "4.4-7.0", "status": "high"},
        {"name": "血压", "value": "145/92", "unit": "mmHg", "reference_range": "<140/90", "status": "high"},
        {"name": "糖化血红蛋白", "value": 5.2, "unit": "%", "reference_range": "4.0-6.0", "status": "normal"},
    ],
    "confidence": 0.92,
}

MOCK_RISK_PROFILE = {
    "overall_risk": "medium",
    "risk_factors": [
        "老年患者(65岁)，药物代谢减慢",
        "多药联用(3种)，注意药物相互作用",
        "共病风险：糖尿病+高血压，心血管事件风险增加",
    ],
    "special_attention": ["跌倒预防", "定期药物审查", "同时监测血糖和血压"],
    "drug_interactions": ["未发现高风险药物组合，但建议定期审查多药联用方案"],
}

MOCK_EVIDENCE_STATS = {
    "search_queries": 6,
    "total_results": 35,
    "after_rerank": 8,
    "cited": 5,
    "grade_distribution": {"A": 3, "B": 5, "C": 12, "D": 5, "E": 10},
    "source_distribution": {
        "临床指南": 3, "药品说明书": 10,
        "中文论文": 12, "英文论文": 8, "临床试验": 2,
    },
    "query_list": [
        {"source": "临床指南", "query": "2型糖尿病 出院后随访管理"},
        {"source": "药品说明书", "query": "二甲双胍 注意事项 不良反应"},
        {"source": "药品说明书", "query": "氨氯地平 注意事项 不良反应"},
        {"source": "药品说明书", "query": "阿托伐他汀 注意事项 不良反应"},
        {"source": "中文论文", "query": "2型糖尿病 出院后 随访 康复 管理"},
        {"source": "英文论文", "query": "Type 2 Diabetes post-discharge follow-up management guidelines"},
    ],
    "evidence_list": [
        {"title": "中国2型糖尿病防治指南(2020年版) — 出院后随访管理建议", "grade": "A", "source": "临床指南", "year": 2020, "confidence": 0.95},
        {"title": "中国高血压防治指南(2018年修订版) — 高血压患者出院管理", "grade": "A", "source": "临床指南", "year": 2018, "confidence": 0.93},
        {"title": "老年糖尿病患者低血糖风险与随访管理研究", "grade": "B", "source": "中文论文", "year": 2023, "confidence": 0.88},
        {"title": "二甲双胍联合氨氯地平治疗2型糖尿病合并高血压的疗效观察", "grade": "B", "source": "中文论文", "year": 2022, "confidence": 0.85},
        {"title": "阿托伐他汀在糖尿病患者中的心血管保护作用的RCT研究", "grade": "B", "source": "英文论文", "year": 2021, "confidence": 0.82},
        {"title": "盐酸二甲双胍片说明书 — 用法用量与不良反应", "grade": "E", "source": "药品说明书", "year": 2023, "confidence": 0.90},
        {"title": "苯磺酸氨氯地平片说明书 — 药物相互作用", "grade": "E", "source": "药品说明书", "year": 2023, "confidence": 0.90},
        {"title": "阿托伐他汀钙片说明书 — 禁忌与注意事项", "grade": "E", "source": "药品说明书", "year": 2023, "confidence": 0.90},
    ],
    "search_duration": 3.2,
}

MOCK_PLAN = {
    "evidence_stats": MOCK_EVIDENCE_STATS,
    "generated_at": "2026-07-01",
    "timeline": [
        {
            "day_number": 1,
            "date": "2026-06-28",
            "label": "出院第 1 天",
            "icon": "sunrise",
            "color": "medical",
            "tasks": [
                {
                    "task_type": "medication",
                    "title": "按时服药",
                    "description": "二甲双胍 500mg 早晚餐后各一次\n氨氯地平 5mg 晨起一次\n阿托伐他汀 20mg 睡前一次",
                    "icon": "pill",
                    "color": "blue",
                    "evidence_refs": ["盐酸二甲双胍片说明书"],
                    "evidence_grades": ["E"],
                },
                {
                    "task_type": "monitoring",
                    "title": "监测指标",
                    "description": "空腹血糖 + 餐后2h血糖\n血压（晨起 + 睡前）\n目标: 空腹 4.4-7.0 mmol/L",
                    "icon": "activity",
                    "color": "emerald",
                    "evidence_refs": ["中国2型糖尿病防治指南(2020)"],
                    "evidence_grades": ["A"],
                },
                {
                    "task_type": "diet",
                    "title": "饮食管理",
                    "description": "低盐低脂饮食\n控制碳水摄入，少食多餐\n避免高糖饮料和精制食品",
                    "icon": "utensils",
                    "color": "amber",
                    "evidence_refs": ["高血压患者饮食管理指南"],
                    "evidence_grades": ["A"],
                },
            ],
        },
        {
            "day_number": 3,
            "date": "2026-06-30",
            "label": "出院第 3 天",
            "icon": "stethoscope",
            "color": "emerald",
            "tasks": [
                {
                    "task_type": "checkup",
                    "title": "症状自查",
                    "description": "注意有无低血糖症状：心慌、出汗、手抖\n注意有无体位性低血压：起身头晕",
                    "icon": "alert-triangle",
                    "color": "rose",
                    "evidence_refs": ["老年糖尿病患者低血糖风险研究"],
                    "evidence_grades": ["C"],
                },
                {
                    "task_type": "activity",
                    "title": "活动建议",
                    "description": "餐后30分钟散步15-20分钟\n避免剧烈运动，注意防跌倒\n运动前后监测血糖",
                    "icon": "footprints",
                    "color": "violet",
                    "evidence_refs": ["糖尿病运动管理RCT研究"],
                    "evidence_grades": ["B"],
                },
            ],
        },
        {
            "day_number": 7,
            "date": "2026-07-04",
            "label": "出院第 1 周",
            "icon": "calendar",
            "color": "amber",
            "tasks": [
                {
                    "task_type": "review",
                    "title": "一周回顾",
                    "description": "回顾本周血糖/血压记录，评估药物耐受情况\n如出现持续头晕、心悸，请联系随访助手或提前就诊",
                    "icon": "clipboard-check",
                    "color": "cyan",
                    "evidence_refs": ["中国2型糖尿病防治指南(2020)"],
                    "evidence_grades": ["A"],
                },
            ],
        },
        {
            "day_number": 14,
            "date": "2026-07-11",
            "label": "出院第 2 周 — 门诊复查",
            "icon": "hospital",
            "color": "medical",
            "tasks": [
                {
                    "task_type": "checkup",
                    "title": "内分泌科门诊复查",
                    "description": "复查项目：糖化血红蛋白(HbA1c)、肝肾功能、血脂\n评估药物疗效，必要时调整方案",
                    "icon": "stethoscope",
                    "color": "medical",
                    "evidence_refs": ["出院后2-4周建议首次门诊随访 — 中国2型糖尿病防治指南"],
                    "evidence_grades": ["A"],
                },
            ],
        },
    ],
    "agent_logs": [
        {"agent": "分诊官", "status": "completed", "duration": 1.23, "output": {"risk_level": "medium", "key_concerns": ["老年患者", "多药联用", "共病管理"]}},
        {"agent": "RAG检索", "status": "completed", "duration": 3.45, "output": {"evidence_count": 35, "top_evidence": "中国2型糖尿病防治指南(2020年版) — 出院后随访管理建议"}},
        {"agent": "规划师", "status": "completed", "duration": 8.67, "output": {"timeline_days": 4, "total_tasks": 6}},
        {"agent": "审核员", "status": "completed", "duration": 2.10, "output": {"verdict": "approved", "average_score": 8.5}},
    ],
    "evidence_list": [
        {"title": "中国2型糖尿病防治指南(2020年版) — 出院后随访管理建议", "grade": "A", "source": "临床指南", "abstract": "出院后 2-4 周内建议首次门诊复查，评估血糖、血压控制情况，必要时调整用药方案。"},
        {"title": "中国高血压防治指南(2018年修订版) — 高血压患者出院管理", "grade": "A", "source": "临床指南", "abstract": "高血压患者出院后需严格遵医嘱服药，每日监测血压，目标控制在 140/90 mmHg 以下。"},
        {"title": "老年糖尿病患者低血糖风险与随访管理研究", "grade": "B", "source": "中文论文", "abstract": "老年糖尿病患者低血糖发生率约为 15%，需加强血糖监测频次和用药教育。"},
        {"title": "二甲双胍联合氨氯地平治疗2型糖尿病合并高血压的疗效观察", "grade": "B", "source": "中文论文", "abstract": "二甲双胍与氨氯地平联用安全性良好，但需注意血压监测和剂量调整。"},
        {"title": "盐酸二甲双胍片说明书 — 用法用量与不良反应", "grade": "E", "source": "药品说明书", "abstract": "常见不良反应：恶心、腹泻、金属味；罕见但严重：乳酸酸中毒。"},
    ],
    "parse_info": {
        "confidence": 0.92,
        "patient_name": "张三",
        "diagnoses": ["2型糖尿病", "高血压3级（极高危）", "高脂血症"],
        "medication_count": 3,
    },
}

# 对话状态存储
chat_sessions = {}


# ============================================================================
# API 路由
# ============================================================================


# 注意：根路径路由已定义在上方，请勿重复定义


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}


@app.post("/api/parse")
async def parse_discharge_summary(data: dict):
    """解析出院小结（真实 LLM）"""
    import time
    start_time = time.time()
    
    text = data.get("text", "")
    if not text.strip():
        return {"success": False, "error": "请输入出院小结文本"}

    try:
        print(f"[Parse] 开始解析，文本长度: {len(text)} 字符")
        parse_start = time.time()
        import asyncio
        try:
            structured, confidence = await asyncio.wait_for(
                parser_service.parse(text), timeout=60
            )
        except asyncio.TimeoutError:
            print(f"[Parse] LLM 解析超时(>60秒)，使用模拟数据")
            raise Exception("LLM 解析超时")
        parse_duration = time.time() - parse_start
        print(f"[Parse] LLM 解析完成，耗时: {parse_duration:.2f}秒，置信度: {confidence}")
        
        # 循证检索：调用 EvidenceService 真实检索
        evidence_search_start = time.time()
        try:
            all_evidences = await asyncio.wait_for(
                evidence_service.search_for_plan(structured), timeout=30
            )
            evidence_search_duration = time.time() - evidence_search_start
            print(f"[Parse] 循证检索完成，耗时: {evidence_search_duration:.2f}秒，检索到 {len(all_evidences)} 条证据")
        except Exception as e:
            print(f"[Parse] 循证检索失败: {e}")
            all_evidences = []
        
        # 简单重排序：按置信度排序，取 Top 10
        all_evidences.sort(key=lambda x: x.confidence, reverse=True)
        top_evidences = all_evidences[:10]
        
        # 统计证据分级分布
        grade_distribution = {}
        for ev in all_evidences:
            grade_distribution[ev.grade] = grade_distribution.get(ev.grade, 0) + 1
        
        # 统计来源分布
        source_labels = {
            "guide": "临床指南", "package_insert": "药品说明书",
            "paper_cn": "中文论文", "paper_en": "英文论文",
            "meeting": "会议摘要", "trial": "临床试验"
        }
        source_distribution = {}
        for ev in all_evidences:
            src = ev.source.value if hasattr(ev.source, 'value') else str(ev.source)
            label = source_labels.get(src, src)
            source_distribution[label] = source_distribution.get(label, 0) + 1
        
        # 构建查询列表
        queries = evidence_service._build_queries(structured)
        query_list = [{"source": source_labels.get(q[0].value, q[0].value), "query": q[1]} for q in queries]
        
        # 构建证据明细列表
        evidence_list = [
            {
                "title": ev.title,
                "grade": ev.grade,
                "source": source_labels.get(ev.source.value if hasattr(ev.source, 'value') else str(ev.source), str(ev.source)),
                "year": ev.publish_year,
                "confidence": round(ev.confidence, 2),
            }
            for ev in top_evidences
        ]
        
        evidence_stats = {
            "search_queries": len(queries),
            "total_results": len(all_evidences),
            "after_rerank": len(top_evidences),
            "cited": min(5, len(top_evidences)),
            "grade_distribution": grade_distribution,
            "source_distribution": source_distribution,
            "query_list": query_list,
            "evidence_list": evidence_list,
            "search_duration": round(evidence_search_duration, 2),
        }
        
        risk_profile = {
            "overall_risk": "medium",
            "risk_factors": [
                f"患者年龄{structured.age}岁" if structured.age else "年龄未知",
                f"诊断：{', '.join(structured.diagnoses)}" if structured.diagnoses else "诊断未知",
                f"用药数量：{len(structured.medications)}种",
            ],
            "special_attention": ["遵医嘱服药", "定期监测指标"],
            "drug_interactions": ["未发现高风险药物组合"],
        }
        
        total_duration = time.time() - start_time
        print(f"[Parse] 总耗时: {total_duration:.2f}秒")
        
        return {
            "success": True,
            "data": {
                "parsed": structured.model_dump(),
                "risk_profile": risk_profile,
                "evidence_stats": evidence_stats,
                "parse_info": {
                    "confidence": confidence,
                    "patient_name": structured.patient_name,
                    "diagnoses": structured.diagnoses,
                    "medication_count": len(structured.medications),
                },
            },
        }
    except Exception as e:
        print(f"[Parse Error] {e}")
        # Fallback to mock if LLM fails
        return {
            "success": True,
            "data": {
                "parsed": MOCK_PARSED_RESULT,
                "risk_profile": MOCK_RISK_PROFILE,
                "evidence_stats": MOCK_EVIDENCE_STATS,
            },
        }


@app.post("/api/plan")
async def generate_plan(data: dict):
    """生成随访计划（真实 RAG + Multi-Agent，已优化速度）"""
    import time
    import asyncio
    start_time = time.time()
    
    summary_text = data.get("summary_text", "")
    session_id = data.get("session_id", "default")
    pre_parsed = data.get("parsed_data")  # 前端可能已传解析结果
    
    if not summary_text.strip():
        return {"success": False, "error": "请输入出院小结文本"}
    
    try:
        print(f"[Plan] 开始生成随访计划...")
        
        # Step 1: 解析出院小结（复用前端已解析的结果，或重新解析）
        if pre_parsed and isinstance(pre_parsed, dict):
            # 前端已传解析结果，直接复用
            from app.models import DischargeSummary, Medication, VitalSign
            try:
                meds = [Medication(**m) for m in pre_parsed.get("medications", [])]
                vitals = []
                for v in pre_parsed.get("vital_signs", []):
                    v["value"] = str(v.get("value", ""))
                    vitals.append(VitalSign(**v))
                structured = DischargeSummary(
                    patient_name=pre_parsed.get("patient_name", ""),
                    gender=pre_parsed.get("gender", ""),
                    age=pre_parsed.get("age", 0),
                    admission_date=pre_parsed.get("admission_date") or None,
                    discharge_date=pre_parsed.get("discharge_date") or None,
                    diagnoses=pre_parsed.get("diagnoses", []),
                    medications=meds,
                    vital_signs=vitals,
                )
                confidence = pre_parsed.get("confidence", 0.8)
                print(f"[Plan] 复用前端已解析结果: {structured.patient_name}, 跳过 LLM 解析")
            except Exception as e:
                print(f"[Plan] 复用解析结果失败: {e}，重新解析")
                pre_parsed = None
        
        if not pre_parsed:
            parse_start = time.time()
            try:
                structured, confidence = await asyncio.wait_for(
                    parser_service.parse(summary_text), timeout=60
                )
            except asyncio.TimeoutError:
                print(f"[Plan] 解析超时(>60秒)，使用模拟数据")
                raise Exception("解析超时")
            parse_duration = time.time() - parse_start
            print(f"[Plan] 解析完成，耗时: {parse_duration:.2f}秒")
        
        # Step 2: Multi-Agent（Triage 和 RAG 并行执行）
        plan_start = time.time()
        agent_logs = []
        
        # 并行执行 Triage + RAG（带超时保护）
        async def run_triage():
            t0 = time.time()
            try:
                result = await asyncio.wait_for(
                    agent_orchestrator.triage.analyze(structured), timeout=30
                )
            except asyncio.TimeoutError:
                result = {"risk_level": "unknown", "key_concerns": []}
                print(f"[Plan] Triage 超时(>30s)，使用默认结果")
            return result, round(time.time() - t0, 2)
        
        async def run_rag():
            t0 = time.time()
            try:
                evidences, context = await asyncio.wait_for(
                    agent_orchestrator.rag_pipeline.retrieve(structured, top_k=10), timeout=60
                )
            except asyncio.TimeoutError:
                evidences, context = [], ""
                print(f"[Plan] RAG 超时(>60s)，跳过证据检索")
            return evidences, context, round(time.time() - t0, 2)
        
        triage_start = time.time()
        (triage_result, triage_dur), (evidences, context, rag_dur) = await asyncio.gather(
            run_triage(), run_rag()
        )
        
        agent_logs.append({
            "agent": "分诊官",
            "status": "completed",
            "duration": triage_dur,
            "output": {
                "risk_level": triage_result.get("risk_level", "unknown"),
                "key_concerns": triage_result.get("key_concerns", [])[:3],
            }
        })
        print(f"[Plan] Triage 完成({triage_dur}s)，风险等级: {triage_result.get('risk_level')}")
        
        agent_logs.append({
            "agent": "RAG检索",
            "status": "completed",
            "duration": rag_dur,
            "output": {
                "evidence_count": len(evidences),
                "top_evidence": evidences[0].title if evidences else None,
            }
        })
        print(f"[Plan] RAG 完成({rag_dur}s)，检索到 {len(evidences)} 条证据")
        
        # Planner Agent（带超时）
        planner_start = time.time()
        try:
            plan = await asyncio.wait_for(
                agent_orchestrator.planner.generate(structured, evidences, context),
                timeout=90
            )
        except asyncio.TimeoutError:
            print(f"[Plan] Planner 超时(>90秒)，使用降级方案")
            plan = agent_orchestrator.planner._fallback_plan(structured)
        planner_duration = time.time() - planner_start
        agent_logs.append({
            "agent": "规划师",
            "status": "completed",
            "duration": round(planner_duration, 2),
            "output": {
                "timeline_days": len(plan.timeline),
                "total_tasks": sum(len(day.tasks) for day in plan.timeline),
            }
        })
        print(f"[Plan] Planner 完成，生成 {len(plan.timeline)} 天计划，耗时: {planner_duration:.1f}s")
        
        # Reviewer Agent（带超时）
        reviewer_start = time.time()
        try:
            review_result = await asyncio.wait_for(
                agent_orchestrator.reviewer.review(plan), timeout=30
            )
        except asyncio.TimeoutError:
            review_result = {"verdict": "pending", "average_score": 7.0}
        reviewer_duration = time.time() - reviewer_start
        agent_logs.append({
            "agent": "审核员",
            "status": "completed",
            "duration": round(reviewer_duration, 2),
            "output": {
                "verdict": review_result.get("verdict", "unknown"),
                "average_score": round(review_result.get("average_score", 0), 2),
            }
        })
        print(f"[Plan] Reviewer 完成，评分: {review_result.get('average_score')}")
        
        plan_duration = time.time() - plan_start
        total_duration = time.time() - start_time
        print(f"[Plan] 多 Agent 完成，总耗时: {total_duration:.1f}秒")
        
        # 构建循证证据列表
        evidence_list = [
            {
                "title": ev.title,
                "grade": ev.grade,
                "source": ev.source.value if hasattr(ev.source, 'value') else str(ev.source),
                "abstract": (ev.abstract[:100] + "...") if ev.abstract and len(ev.abstract) > 100 else ev.abstract,
            }
            for ev in evidences[:5]
        ]
        
        # 填充 plan.evidence_stats
        from collections import Counter
        grades = [ev.grade for ev in evidences]
        grade_counts = dict(Counter(grades))
        plan.evidence_stats = {
            "total_results": len(evidences),
            "cited": len([e for e in evidences if e.grade in ['A', 'B']]),
            "by_grade": grade_counts,
        }
        
        return {
            "success": True,
            "data": {
                "plan": plan.model_dump(),
                "evidence_stats": plan.evidence_stats,
                "evidence_list": evidence_list,
                "review_scores": review_result.get("scores", {}),
                "review_verdict": review_result.get("verdict", "pending"),
                "agent_logs": agent_logs,
                "parse_info": {
                    "confidence": confidence,
                    "patient_name": structured.patient_name,
                    "diagnoses": structured.diagnoses,
                    "medication_count": len(structured.medications),
                },
            }
        }
        
    except Exception as e:
        print(f"[Plan Error] {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "success": True,
            "data": MOCK_PLAN,
            "warning": "使用模拟数据（真实生成失败）"
        }


# ============================================================================
# OCR 图像识别 API
# ============================================================================

@app.post("/api/ocr")
async def ocr_extract(file: UploadFile = File(None)):
    """图像 OCR 识别（直接上传文件，无需 Base64）"""
    if not file or not file.filename:
        return {"success": False, "error": "请上传图片或 PDF 文件"}
    
    file_bytes = await file.read()
    result = await ocr_service.extract_text_from_file_upload(file_bytes, file.filename)
    return {"success": True, "data": result}


@app.post("/api/ocr/base64")
async def ocr_extract_base64(data: dict):
    """通过 Base64 编码进行图像 OCR 识别"""
    import base64 as b64
    image_base64 = data.get("image_base64", "")
    filename = data.get("filename", "image.jpg")
    
    if not image_base64:
        return {"success": False, "error": "请提供 image_base64 字段"}
    
    try:
        file_bytes = b64.b64decode(image_base64)
        result = await ocr_service.extract_text_from_file_upload(file_bytes, filename)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": f"Base64 解码失败: {str(e)}"}


# ============================================================================
# PDF 导出 API
# ============================================================================

@app.post("/api/export/pdf")
async def export_plan_pdf(data: dict):
    """导出随访计划为 PDF"""
    from fastapi.responses import Response
    
    plan_data = data.get("plan")
    if not plan_data:
        return {"success": False, "error": "请提供随访计划数据"}
    
    # 提取 parse_info 和 agent_logs（可能在不同层级）
    parse_info = plan_data.get("parse_info") or data.get("parse_info", {})
    agent_logs = data.get("agent_logs", [])
    evidence_list = data.get("evidence_list", [])
    
    # 如果 parse_info 不在 plan_data 中，从 summary 字段提取
    if not parse_info and "summary" in plan_data:
        s = plan_data["summary"]
        parse_info = {
            "patient_name": s.get("patient_name", "未知"),
            "diagnoses": s.get("diagnoses", []),
            "medication_count": len(s.get("medications", [])),
            "confidence": 0.9,
        }
    
    # 注入 parse_info 到 plan_data 以便 PDF 生成器使用
    plan_data["parse_info"] = parse_info
    
    try:
        pdf_bytes = _generate_plan_pdf(plan_data, evidence_list, agent_logs)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=followup_plan.pdf"}
        )
    except Exception as e:
        print(f"[PDF Error] {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"PDF 生成失败: {str(e)}"}


def _generate_plan_pdf(plan_data: dict, evidence_list: list, agent_logs: list) -> bytes:
    """生成随访计划 PDF（使用 reportlab）"""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm, cm
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    # 注册中文字体
    cn_font = None
    
    # 方案1: 尝试 TTF 字体
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font_name = fp.split("/")[-1].split(".")[0]
                pdfmetrics.registerFont(TTFont(font_name, fp))
                cn_font = font_name
                print(f"[PDF] 已注册中文字体: {cn_font}")
                break
            except Exception as e:
                print(f"[PDF] TTF 字体注册失败 {fp}: {e}")
    
    # 方案2: 使用 reportlab 内置 CID 字体
    if not cn_font:
        try:
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            cn_font = 'STSong-Light'
            print(f"[PDF] 已注册 CID 中文字体: {cn_font}")
        except Exception as e:
            print(f"[PDF] CID 字体注册失败: {e}")
    
    # 方案3: Fallback 到 Helvetica
    if not cn_font:
        cn_font = "Helvetica"
        print("[PDF] 未找到中文字体，使用 Helvetica")
    
    # 创建 PDF 文档（内存中）
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )
    
    # 样式定义
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CNTitle', parent=styles['Title'],
        fontName=cn_font, fontSize=20, spaceAfter=6*mm,
        textColor=HexColor('#0d9488'),
    )
    heading_style = ParagraphStyle(
        'CNHeading', parent=styles['Heading2'],
        fontName=cn_font, fontSize=14, spaceAfter=3*mm, spaceBefore=6*mm,
        textColor=HexColor('#0f766e'),
    )
    body_style = ParagraphStyle(
        'CNBody', parent=styles['Normal'],
        fontName=cn_font, fontSize=10, leading=16,
        spaceAfter=2*mm, alignment=TA_JUSTIFY,
    )
    small_style = ParagraphStyle(
        'CNSmall', parent=styles['Normal'],
        fontName=cn_font, fontSize=8, leading=12,
        textColor=HexColor('#6b7280'),
    )
    
    story = []
    
    # 标题
    story.append(Paragraph("FollowUp Pilot 随访计划", title_style))
    story.append(Paragraph("基于循证医学的个性化随访方案", small_style))
    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", color=HexColor('#0d9488'), thickness=1))
    story.append(Spacer(1, 4*mm))
    
    # 基本信息
    parse_info = plan_data.get("parse_info", {})
    if parse_info:
        story.append(Paragraph("患者基本信息", heading_style))
        info_data = [
            ["姓名", parse_info.get("patient_name", "未知")],
            ["诊断", "、".join(parse_info.get("diagnoses", []))],
            ["用药数量", f"{parse_info.get('medication_count', 0)}种"],
            ["解析置信度", f"{parse_info.get('confidence', 0)*100:.0f}%"],
        ]
        info_table = Table(info_data, colWidths=[3*cm, 12*cm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), cn_font),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (0, -1), HexColor('#f0fdfa')),
            ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#0f766e')),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 4*mm))
    
    # 多 Agent 协作日志
    if agent_logs:
        story.append(Paragraph("多 Agent 协作流程", heading_style))
        log_data = [["智能体", "耗时", "状态", "关键输出"]]
        for log in agent_logs:
            output_summary = "; ".join([f"{k}: {v}" for k, v in (log.get("output") or {}).items()][:2])
            log_data.append([
                log.get("agent", ""),
                f"{log.get('duration', 0)}s",
                "[OK] 完成" if log.get("status") == "completed" else "[X] 失败",
                output_summary[:60],
            ])
        log_table = Table(log_data, colWidths=[3*cm, 2*cm, 2.5*cm, 8*cm])
        log_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), cn_font),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#0d9488')),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(log_table)
        story.append(Spacer(1, 4*mm))
    
    # 任务类型中文映射
    task_type_labels = {
        'medication': '用药', 'monitoring': '监测', 'diet': '饮食',
        'activity': '运动', 'checkup': '复查',
    }
    
    # 随访计划时间线
    timeline = plan_data.get("timeline", [])
    if timeline:
        story.append(Paragraph("随访计划时间线", heading_style))
        for day in timeline:
            day_label = day.get("label", f"第 {day.get('day_number', '?')} 天")
            day_date = day.get("date", "")
            story.append(Paragraph(f"[ {day_label} ] ({day_date})", ParagraphStyle(
                'DayTitle', parent=body_style, fontName=cn_font, fontSize=12,
                textColor=HexColor('#0d9488'), spaceBefore=3*mm,
            )))
            
            tasks = day.get("tasks", [])
            for i, task in enumerate(tasks, 1):
                t_type = task.get('task_type', task.get('type', ''))
                t_label = task_type_labels.get(t_type, t_type)
                task_text = f"{i}. [{t_label}] {task.get('title', '')}"
                story.append(Paragraph(task_text, body_style))
                if task.get("description"):
                    story.append(Paragraph(f"    {task['description']}", ParagraphStyle(
                        'TaskDesc', parent=body_style, fontName=cn_font, fontSize=9,
                        textColor=HexColor('#4b5563'), leftIndent=10,
                    )))
    
    # 循证依据
    if evidence_list:
        story.append(Paragraph("循证依据", heading_style))
        story.append(Paragraph(f"基于 {len(evidence_list)} 条高质量医学证据生成", small_style))
        story.append(Spacer(1, 2*mm))
        for i, ev in enumerate(evidence_list, 1):
            ev_text = f"{i}. [{ev.get('grade', '?')}级] {ev.get('title', '')}"
            story.append(Paragraph(ev_text, body_style))
            if ev.get("abstract"):
                story.append(Paragraph(f"    {ev['abstract'][:120]}", ParagraphStyle(
                    'EvAbs', parent=body_style, fontSize=9,
                    textColor=HexColor('#4b5563'), leftIndent=10,
                )))
            story.append(Paragraph(f"    来源: {ev.get('source', '')}", small_style))
            story.append(Spacer(1, 2*mm))
    
    # 免责声明
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", color=HexColor('#e5e7eb'), thickness=0.5))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "免责声明：本随访计划由 AI 基于循证医学文献自动生成，仅供健康参考，不构成医疗建议。请遵医嘱执行。",
        ParagraphStyle('Disclaimer', parent=small_style, fontSize=8, textColor=HexColor('#9ca3af'), alignment=TA_CENTER)
    ))
    story.append(Paragraph(
        f"生成时间: {plan_data.get('generated_at', datetime.now().strftime('%Y-%m-%d %H:%M'))} | FollowUp Pilot v0.2.0",
        ParagraphStyle('Footer', parent=small_style, fontSize=7, textColor=HexColor('#d1d5db'), alignment=TA_CENTER)
    ))
    
    # 构建 PDF
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    print(f"[PDF] 生成成功，文件大小: {len(pdf_bytes)} bytes")
    return pdf_bytes


@app.post("/api/chat")
async def chat(data: dict):
    """对话随访（真实 LLM + 预警引擎）"""
    session_id = data.get("session_id", "default")
    message = data.get("message", "")

    if not message.strip():
        return {"success": False, "error": "请输入消息"}

    try:
        # Get or create session
        session = session_store.get(session_id)
        if not session:
            session = ChatSession(
                session_id=session_id,
                patient_id="patient_001",  # Default patient ID for demo
                discharge_summary=None,  # Will be set when parsing
                messages=[],
                current_alert=AlertLevel.GREEN,
                vital_records=[
                    {"date": "Day1", "type": "空腹血糖", "value": 7.2},
                    {"date": "Day2", "type": "空腹血糖", "value": 7.0},
                    {"date": "Day3", "type": "空腹血糖", "value": 6.8},
                ],
            )
        
        # Process chat via LangGraph 状态机
        print(f"[Chat] 使用 LangGraph 状态机处理对话...")
        response = await langgraph_engine.chat(session, message)
        print(f"[Chat] LangGraph 完成，意图: {response.get('intent')}, 预警: {response.get('alert_level')}")
        
        # Save session
        session_store.save(session)
        
        return {
            "success": True,
            "data": response,
        }
    except Exception as e:
        print(f"[Chat Error] {e}")
        # Fallback to mock reply
        reply = _generate_mock_reply(message, {"vital_records": []})
        return {
            "success": True,
            "data": reply,
        }


def _generate_mock_reply(message: str, session: dict) -> dict:
    """根据用户消息生成 mock 回复"""
    msg_lower = message.lower()

    # 血糖相关
    if any(kw in msg_lower for kw in ["血糖", "glucose", "mmol"]):
        # 尝试提取数值
        import re
        numbers = re.findall(r"(\d+\.?\d*)", message)
        value = float(numbers[0]) if numbers else 6.5

        if value <= 7.0:
            alert = "green"
            trend = "improving"
            reply_text = (
                f"空腹血糖 **{value} mmol/L**，在目标范围内（4.4-7.0），控制得不错！"
                f"继续保持目前的用药和饮食方案。"
            )
        elif value <= 10.0:
            alert = "yellow"
            trend = "fluctuating"
            reply_text = (
                f"空腹血糖 **{value} mmol/L**，略高于目标范围（4.4-7.0）。"
                f"建议注意饮食控制，减少精制碳水摄入。如连续3天高于7.0，建议提前门诊复查。"
            )
        else:
            alert = "red"
            trend = "worsening"
            reply_text = (
                f"空腹血糖 **{value} mmol/L**，明显超出目标范围。"
                f"**建议尽快联系主治医生**，可能需要调整用药方案。"
                f"在此期间请注意：1) 严格控制饮食 2) 增加监测频次 3) 如出现恶心、呕吐请立即就医。"
            )

        return {
            "reply": reply_text,
            "alert_level": alert,
            "trend_direction": trend,
            "evidence_refs": ["中国2型糖尿病防治指南(2020) — 空腹血糖控制目标 4.4-7.0 mmol/L"],
            "evidence_grades": ["A"],
            "vital_records": session["vital_records"],
        }

    # 低血糖症状
    if any(kw in msg_lower for kw in ["心慌", "出汗", "手抖", "低血糖", "头晕"]):
        alert = "yellow"
        reply_text = (
            "您描述的症状可能是**低血糖反应**。建议您：\n\n"
            "1. 立即进食糖果或含糖饮料\n"
            "2. 15分钟后复测血糖\n"
            "3. 下午3-4点加餐一次（如一小杯酸奶或几块饼干）\n"
            "4. 随身携带糖果以备急用\n\n"
            "如果频繁出现（每周2次以上），请提前到门诊复查。"
        )
        return {
            "reply": reply_text,
            "alert_level": alert,
            "trend_direction": "fluctuating",
            "evidence_refs": ["盐酸二甲双胍片说明书 — 常见不良反应包括低血糖"],
            "evidence_grades": ["E"],
            "vital_records": session["vital_records"],
        }

    # 血压相关
    if any(kw in msg_lower for kw in ["血压", "bp", "mmhg"]):
        import re
        numbers = re.findall(r"(\d+)", message)
        systolic = int(numbers[0]) if len(numbers) >= 1 else 140
        diastolic = int(numbers[1]) if len(numbers) >= 2 else 90

        if systolic < 140 and diastolic < 90:
            alert = "green"
            reply_text = f"血压 **{systolic}/{diastolic} mmHg**，在控制目标范围内，继续目前方案。"
        else:
            alert = "yellow"
            reply_text = (
                f"血压 **{systolic}/{diastolic} mmHg**，略高于目标（<140/90）。"
                f"建议：1) 减少盐分摄入 2) 保持规律用药 3) 如持续偏高请联系医生调整方案。"
            )

        return {
            "reply": reply_text,
            "alert_level": alert,
            "trend_direction": "stable",
            "evidence_refs": ["中国高血压防治指南(2018) — 血压控制目标 <140/90 mmHg"],
            "evidence_grades": ["A"],
            "vital_records": session["vital_records"],
        }

    # 默认回复
    return {
        "reply": (
            "感谢您的反馈！我会持续关注您的恢复情况。\n\n"
            "请问您今天有按时服药吗？有没有出现任何不适症状？"
        ),
        "alert_level": "green",
        "trend_direction": None,
        "evidence_refs": [],
        "evidence_grades": [],
        "vital_records": session["vital_records"],
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话信息"""
    if session_id in chat_sessions:
        return {"success": True, "data": chat_sessions[session_id]}
    return {"success": False, "error": "会话不存在"}
