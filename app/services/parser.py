"""M1: 出院小结解析服务"""

import json
from app.models import DischargeSummary, Medication
from app.tools.llm_gateway import LLMGateway

PARSER_SYSTEM_PROMPT = """你是一个专业的医疗文书解析助手。
你的任务是从出院小结中提取结构化信息。

**极其重要：你必须输出纯 JSON 格式，字段名必须与下面示例完全一致！**

正确的 JSON 输出示例（请严格模仿这个格式）：
{
  "patient_name": "张三",
  "gender": "男",
  "age": 65,
  "admission_date": null,
  "discharge_date": null,
  "diagnoses": ["2型糖尿病", "高血压3级"],
  "medications": [
    {"name": "二甲双胍", "dosage": "500mg", "frequency": "每日两次", "timing": "餐后"},
    {"name": "氨氯地平", "dosage": "5mg", "frequency": "每日一次", "timing": "晨起"}
  ],
  "vital_signs": [
    {"name": "空腹血糖", "value": "7.8", "unit": "mmol/L", "reference_range": "3.9-6.1", "status": "high"},
    {"name": "血压", "value": "145/92", "unit": "mmHg", "reference_range": "<140/90", "status": "high"}
  ],
  "chief_complaint": "",
  "treatment_summary": "",
  "discharge_instructions": ""
}

**字段说明：**
- patient_name: 患者姓名（字符串，必填）
- gender: 性别（"男" 或 "女"，必填）
- age: 年龄（整数数字，必填，如 65）
- admission_date: 入院日期（YYYY-MM-DD 格式，如果文中没有则填 null）
- discharge_date: 出院日期（YYYY-MM-DD 格式，如果文中没有则填 null）
- diagnoses: 诊断列表（字符串数组，即使只有一个也要用数组）
- medications: 用药列表（数组），每个元素包含 name/dosage/frequency/timing
- vital_signs: 生命体征列表（数组），每个元素包含 name/value/unit/reference_range/status
- chief_complaint: 主诉（字符串，如果没有填空字符串 ""）
- treatment_summary: 治疗经过（字符串，如果没有填空字符串 ""）
- discharge_instructions: 出院医嘱（字符串，如果没有填空字符串 ""）

**关键规则（违反会导致系统错误）：**
1. ⚠️ **字段名必须与上面示例完全一致**，不能自己创造字段名（如不能用 "," 代替 "patient_name"）
2. ⚠️ **只输出纯 JSON**，不要有任何额外文字、解释、markdown 格式或代码块标记（```json）
3. ⚠️ **JSON 必须是合法的**，确保所有引号、逗号、括号都正确配对
4. patient_name、gender、age 是必填字段，绝对不能为空或 null
5. admission_date 和 discharge_date 如果文中没有提到，请填 null（不是空字符串 ""）
6. diagnoses 必须是字符串数组，例如 ["2型糖尿病"] 而不是 "2型糖尿病"
7. medications 中 timing 可以是"餐后"、"晨起"、"睡前"等，如果文中未提及填空字符串 ""
8. vital_signs 中 value 必须是字符串类型（即使是数字也要加引号），status 只能是 "normal"、"high" 或 "low"
9. chief_complaint、treatment_summary、discharge_instructions 如果文中没有提及相关内容，填空字符串 ""

**常见错误示例（千万不要这样输出）：**
❌ 错误1：{"patient_name": "张三"} 后面有多余的逗号或文字
❌ 错误2：{"," : "张三"} 字段名错误
❌ 错误3：```json\n{...}\n``` 包含 markdown 标记
❌ 错误4：{"diagnoses": "2型糖尿病"} 应该是数组 ["2型糖尿病"]

**再次强调：只输出合法的 JSON 对象，不要任何其他内容！**
"""


class ParserService:
    """出院小结解析服务"""

    def __init__(self, llm_client: LLMGateway):
        self.llm = llm_client

    async def parse(self, text: str) -> tuple[DischargeSummary, float]:
        """
        解析出院小结文本。

        Returns:
            (structured_data, confidence_score)
        """
        messages = [
            {"role": "system", "content": PARSER_SYSTEM_PROMPT},
            {"role": "user", "content": f"请解析以下出院小结：\n\n{text}"}
        ]

        response = await self.llm.chat_completion_with_retry(
            messages=messages,
            # 不使用 JSON mode，StepFun 在 JSON mode 下字段名容易出错
            temperature=0.1  # 低温度，保证稳定输出
        )

        # chat_completion 返回的是字符串，需要解析 JSON
        print(f"[Parser] LLM 原始响应: {response[:200]}...")  # 打印前200字符用于调试
        
        try:
            raw_json = json.loads(response) if isinstance(response, str) else response
        except json.JSONDecodeError as e:
            print(f"[Parser] JSON 解析失败: {e}")
            print(f"[Parser] 原始响应前500字符: {response[:500]}")
            # 尝试修复常见的 JSON 格式问题
            response_cleaned = response.strip()
            # 移除可能的 markdown 代码块标记
            if response_cleaned.startswith('```'):
                response_cleaned = response_cleaned.split('```', 1)[1]
                if response_cleaned.endswith('```'):
                    response_cleaned = response_cleaned[:-3]
                response_cleaned = response_cleaned.strip()
                    
            try:
                raw_json = json.loads(response_cleaned)
                print(f"[Parser] JSON 修复成功")
            except json.JSONDecodeError as e2:
                print(f"[Parser] JSON 修复失败: {e2}")
                # 最后一次尝试：提取第一个 { 和最后一个 } 之间的内容
                try:
                    start_idx = response.find('{')
                    end_idx = response.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_str = response[start_idx:end_idx+1]
                        raw_json = json.loads(json_str)
                        print(f"[Parser] 通过提取 JSON 对象修复成功")
                    else:
                        raise ValueError("无法找到有效的 JSON 对象")
                except Exception as e3:
                    print(f"[Parser] 所有修复尝试均失败: {e3}")
                    raise ValueError(f"LLM 返回的 JSON 格式错误: {str(e2)}")
                
        # Step 2: 修复字段名错误（StepFun LLM 已知问题）
        raw_json = self._fix_field_names(raw_json)
                
        structured = DischargeSummary(**raw_json)
        confidence = self._calculate_confidence(structured, text)

        return structured, confidence

    def _fix_field_names(self, data: dict) -> dict:
        """
        修复 LLM 返回的错误字段名
        
        StepFun LLM 有时会将字段名输出为错误的格式，如：
        - "," → "patient_name"
        - ": " → "patient_name"
        - "name" → "patient_name"
        """
        # 定义错误字段名到正确字段名的映射
        field_mapping = {
            ",": "patient_name",
            ": ": "patient_name",
            "name": "patient_name",
            "姓名": "patient_name",
            "gender": "gender",  # 保持不变
            "性别": "gender",
            "age": "age",
            "年龄": "age",
            "admission_date": "admission_date",
            "入院日期": "admission_date",
            "discharge_date": "discharge_date",
            "出院日期": "discharge_date",
            "diagnoses": "diagnoses",
            "诊断": "diagnoses",
            "medications": "medications",
            "用药": "medications",
            "vital_signs": "vital_signs",
            "生命体征": "vital_signs",
            "chief_complaint": "chief_complaint",
            "主诉": "chief_complaint",
            "treatment_summary": "treatment_summary",
            "治疗经过": "treatment_summary",
            "discharge_instructions": "discharge_instructions",
            "出院医嘱": "discharge_instructions",
        }
        
        fixed_data = {}
        for key, value in data.items():
            # 如果字段名在映射表中，使用正确的字段名
            correct_key = field_mapping.get(key, key)
            fixed_data[correct_key] = value
        
        # 检查必需字段是否存在
        required_fields = ["patient_name", "gender", "age"]
        missing_fields = [f for f in required_fields if f not in fixed_data]
        
        if missing_fields:
            print(f"[Parser Warning] 缺少必需字段: {missing_fields}")
            # 尝试从其他字段推断
            if "patient_name" not in fixed_data:
                # 查找可能的姓名字段
                for key in ["姓名", "name", "患者姓名"]:
                    if key in data:
                        fixed_data["patient_name"] = data[key]
                        print(f"[Parser] 从 '{key}' 字段推断出 patient_name")
                        break
        
        return fixed_data
    
    def _calculate_confidence(self, data: DischargeSummary, text: str) -> float:
        """简单置信度评估：核心字段非空即加分"""
        score = 0.0
        if data.diagnoses: score += 0.3  # 修复：使用 diagnoses（复数）
        if data.medications: score += 0.3
        if data.discharge_instructions: score += 0.2  # 修复：使用 discharge_instructions
        if data.vital_signs: score += 0.1  # 修复：使用 vital_signs
        if data.patient_name: score += 0.1
        return min(score, 1.0)
