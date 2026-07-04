#!/usr/bin/env python3
"""
快速测试脚本 - 验证4项优化是否生效
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models import DischargeSummary, Medication, VitalSign
from app.services.parser import ParserService
from app.tools.llm_gateway import LLMGateway
from app.rag.pipeline import RAGPipeline
from app.cache import rag_cache
from app.tools.knows_search import KnowSClient


async def test_parser_optimization():
    """测试1: Parser JSON 解析优化"""
    print("\n" + "="*60)
    print("测试1: Parser JSON 解析优化")
    print("="*60)
    
    llm = LLMGateway()
    parser = ParserService(llm)
    
    test_text = "患者张三，男，65岁。诊断：2型糖尿病、高血压3级。用药：二甲双胍 500mg bid，氨氯地平 5mg qd。空腹血糖7.8mmol/L，血压145/92mmHg。"
    
    try:
        structured, confidence = await parser.parse(test_text)
        print(f"✅ 解析成功！")
        print(f"   患者姓名: {structured.patient_name}")
        print(f"   诊断: {structured.diagnoses}")
        print(f"   置信度: {confidence:.2f}")
        return True
    except Exception as e:
        print(f"❌ 解析失败: {e}")
        return False


async def test_cache_mechanism():
    """测试2: 缓存机制"""
    print("\n" + "="*60)
    print("测试2: 缓存机制")
    print("="*60)
    
    # 清空缓存
    rag_cache.clear()
    print("📦 缓存已清空")
    
    # 创建测试数据
    summary = DischargeSummary(
        patient_name="李四",
        gender="男",
        age=70,
        diagnoses=["冠心病", "心力衰竭"],
        medications=[
            Medication(name="阿司匹林", dosage="100mg", frequency="每日一次", timing="餐后"),
            Medication(name="美托洛尔", dosage="25mg", frequency="每日两次", timing="")
        ],
        vital_signs=[],
        chief_complaint="",
        treatment_summary="",
        discharge_instructions=""
    )
    
    # 第一次调用（未命中缓存）
    cache_key_parts = [
        "|".join(sorted(summary.diagnoses)),
        "|".join(sorted([m.name for m in summary.medications]))
    ]
    
    cached = rag_cache.get(*cache_key_parts)
    if cached is None:
        print("✅ 第一次调用：缓存未命中（预期行为）")
    else:
        print("❌ 第一次调用：意外命中缓存")
        return False
    
    # 模拟写入缓存
    mock_data = ("mock_evidence", "mock_context")
    rag_cache.set(*cache_key_parts, value=mock_data)
    print("💾 已写入缓存")
    
    # 第二次调用（应命中缓存）
    cached = rag_cache.get(*cache_key_parts)
    if cached == mock_data:
        print("✅ 第二次调用：缓存命中！")
        print(f"   缓存内容: {cached}")
        return True
    else:
        print("❌ 第二次调用：缓存未命中")
        return False


async def test_llm_fallback():
    """测试3: LLM 故障转移机制"""
    print("\n" + "="*60)
    print("测试3: LLM 故障转移机制")
    print("="*60)
    
    llm = LLMGateway()
    
    print(f"🔧 当前主提供商: {llm.provider}")
    print(f"🔄 备用提供商列表: {llm.FALLBACK_PROVIDERS.get(llm.provider, [])}")
    
    # 测试正常调用（不应触发故障转移）
    try:
        response = await llm.chat_completion_with_retry(
            messages=[{"role": "user", "content": "请回复'OK'"}],
            temperature=0.0,
        )
        print(f"✅ LLM 调用成功: {response[:50]}...")
        return True
    except Exception as e:
        print(f"⚠️  LLM 调用失败（可能触发故障转移）: {e}")
        return False


def test_frontend_integration():
    """测试4: 前端集成检查"""
    print("\n" + "="*60)
    print("测试4: 前端集成检查")
    print("="*60)
    
    frontend_file = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
    
    if not os.path.exists(frontend_file):
        print(f"❌ 前端文件不存在: {frontend_file}")
        return False
    
    with open(frontend_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ("summary_text 参数", "summary_text:" in content),
        ("session_id 参数", "session_id:" in content),
        ("进度提示", "loading-subtext" in content),
        ("步骤说明", "分诊分析" in content or "证据检索" in content),
    ]
    
    all_passed = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"{status} {check_name}: {'通过' if result else '失败'}")
        if not result:
            all_passed = False
    
    return all_passed


async def main():
    """运行所有测试"""
    print("\n" + "🚀 FollowUp Pilot 优化验证测试")
    print("=" * 60)
    
    results = []
    
    # 测试1: Parser 优化
    results.append(("Parser JSON 解析优化", await test_parser_optimization()))
    
    # 测试2: 缓存机制
    results.append(("缓存机制", await test_cache_mechanism()))
    
    # 测试3: LLM 故障转移
    results.append(("LLM 故障转移", await test_llm_fallback()))
    
    # 测试4: 前端集成
    results.append(("前端集成", test_frontend_integration()))
    
    # 汇总结果
    print("\n" + "="*60)
    print("📊 测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {test_name}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有优化均已成功实施！")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，请检查日志")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
