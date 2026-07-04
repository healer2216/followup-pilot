"""Multi-Agent: 编排器（协调所有 Agent）"""

from app.models import DischargeSummary, FollowUpPlan
from app.tools.knows_search import KnowSClient
from app.tools.llm_gateway import LLMGateway
from ..rag.pipeline import RAGPipeline
from .triage import TriageAgent
from .planner import PlannerAgent
from .reviewer import ReviewerAgent


class AgentOrchestrator:
    """Multi-Agent 编排器"""
    
    def __init__(
        self,
        knows_client: KnowSClient,
        llm_client: LLMGateway
    ):
        self.rag_pipeline = RAGPipeline(knows_client, llm_client)
        self.triage = TriageAgent(llm_client)
        self.planner = PlannerAgent(llm_client)
        self.reviewer = ReviewerAgent(llm_client)
    
    async def generate_plan(
        self, 
        summary: DischargeSummary
    ) -> FollowUpPlan:
        """
        完整流程：
        Triage → RAG Retrieval → Planner → Reviewer
        """
        print("[Orchestrator] Step 1: Triage Analysis...")
        triage_result = await self.triage.analyze(summary)
        print(f"[Orchestrator] Risk level: {triage_result['risk_level']}")
        
        print("[Orchestrator] Step 2: RAG Retrieval...")
        evidences, context = await self.rag_pipeline.retrieve(summary, top_k=10)
        print(f"[Orchestrator] Retrieved {len(evidences)} evidences")
        
        print("[Orchestrator] Step 3: Planning...")
        plan = await self.planner.generate(summary, evidences, context)
        print(f"[Orchestrator] Generated plan with {len(plan.timeline)} timeline days")
        
        print("[Orchestrator] Step 4: Reviewing...")
        review_result = await self.reviewer.review(plan)
        print(f"[Orchestrator] Review verdict: {review_result['verdict']}, Score: {review_result['average_score']}")
        
        # 保存审核结果
        plan.review_verdict = review_result["verdict"]
        plan.review_scores = review_result["scores"]
        
        return plan
