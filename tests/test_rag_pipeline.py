"""测试 RAG Pipeline 和 Multi-Agent"""

import asyncio
import sys
sys.path.insert(0, '/root/study/项目开发/followup-pilot')

from app.config import settings
from app.tools.llm_gateway import LLMGateway
from app.tools.knows_search import KnowSClient
from app.models import DischargeSummary, Medication, VitalSign
from app.rag.pipeline import RAGPipeline
from app.agents.orchestrator import AgentOrchestrator


async def test_rag_pipeline():
    """测试 RAG Pipeline"""
    print("=" * 60)
    print("测试 RAG Pipeline")
    print("=" * 60)
    
    # 初始化
    llm = LLMGateway(provider=settings.LLM_PROVIDER)
    knows = KnowSClient(api_root=settings.KNOWS_BASE_URL)
    
    # 创建测试数据
    summary = DischargeSummary(
        patient_name="张三",
        gender="男",
        age=65,
        diagnoses=["2型糖尿病", "高血压3级"],
        medications=[
            Medication(name="二甲双胍", dosage="500mg", frequency="每日两次"),
            Medication(name="氨氯地平", dosage="5mg", frequency="每日一次"),
        ],
        vital_signs=[
            VitalSign(name="空腹血糖", value="7.8", unit="mmol/L", status="high"),
            VitalSign(name="血压", value="145/92", unit="mmHg", status="high"),
        ]
    )
    
    # 测试 RAG Pipeline
    pipeline = RAGPipeline(knows, llm)
    evidences, context = await pipeline.retrieve(summary, top_k=5)
    
    print(f"\n✅ 检索到 {len(evidences)} 条证据")
    print(f"📄 上下文字符数: {len(context)}")
    
    if evidences:
        print("\n前3条证据:")
        for i, ev in enumerate(evidences[:3]):
            print(f"  {i+1}. [{ev.grade}级] {ev.title[:50]}...")
    
    return evidences, context


async def test_orchestrator():
    """测试完整 Multi-Agent 流程"""
    print("\n" + "=" * 60)
    print("测试 Multi-Agent Orchestrator")
    print("=" * 60)
    
    llm = LLMGateway(provider=settings.LLM_PROVIDER)
    knows = KnowSClient(api_root=settings.KNOWS_BASE_URL)
    
    summary = DischargeSummary(
        patient_name="李四",
        gender="女",
        age=72,
        diagnoses=["冠心病", "心力衰竭"],
        medications=[
            Medication(name="美托洛尔", dosage="25mg", frequency="每日两次"),
            Medication(name="呋塞米", dosage="20mg", frequency="每日一次"),
        ],
        vital_signs=[]
    )
    
    orchestrator = AgentOrchestrator(knows, llm)
    plan = await orchestrator.generate_plan(summary)
    
    print(f"\n✅ 生成随访计划")
    print(f"📅 时间线节点数: {len(plan.timeline)}")
    print(f"📊 审核评分: {plan.review_scores.get('average_score', 'N/A')}")
    print(f"✅ 审核结论: {plan.review_verdict}")
    
    if plan.timeline:
        first_day = plan.timeline[0]
        print(f"\n第1天任务数: {len(first_day.tasks)}")
        for task in first_day.tasks[:2]:
            print(f"  - [{task.task_type}] {task.title}")


if __name__ == "__main__":
    asyncio.run(test_rag_pipeline())
    asyncio.run(test_orchestrator())
