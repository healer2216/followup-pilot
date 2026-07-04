"""
OCR 图像识别服务 - 基于 StepFun Vision 多模态模型
支持出院小结图片 → 文本提取
"""

import base64
import time
from typing import Optional
from openai import AsyncOpenAI
from app.config import config


class OCRService:
    """基于 StepFun step-3.7-flash 的图像 OCR 服务"""

    # OCR 专用 prompt：精确提取出院小结文本
    OCR_PROMPT = """你是一个专业的医疗文档 OCR 识别助手。请仔细阅读这张出院小结图片，完整、准确地提取其中的所有文字内容。

要求：
1. 保持原始文档的结构和格式（如标题、分段、编号列表等）
2. 完整提取所有文字，不要遗漏任何内容
3. 如果文字模糊不清，请尽力识别，无法识别的部分用 [不清] 标注
4. 保持医学术语的准确性
5. 直接输出识别到的文字内容，不要添加额外的解释或说明
6. 特别注意以下关键信息的准确提取：
   - 患者姓名、性别、年龄
   - 入院/出院日期
   - 诊断（入院诊断、出院诊断）
   - 用药方案（药名、剂量、频次）
   - 检验指标数值
   - 出院医嘱
   - 注意事项"""

    def __init__(self):
        # 使用 StepFun 客户端（支持多模态）
        self.api_key = config.STEPFUN_API_KEY or ""
        self.base_url = config.STEPFUN_BASE_URL
        self.model = config.STEPFUN_MODEL  # step-3.7-flash 原生支持多模态
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    async def extract_text_from_image(self, image_base64: str, mime_type: str = "image/jpeg") -> dict:
        """
        从图片中提取出院小结文本

        Args:
            image_base64: 图片的 Base64 编码字符串
            mime_type: 图片 MIME 类型

        Returns:
            {
                "success": True/False,
                "text": 提取的文本内容,
                "confidence": 置信度(0-1),
                "duration": 耗时(秒),
                "error": 错误信息(如有)
            }
        """
        start_time = time.time()

        try:
            print(f"[OCR] 开始图像识别，图片大小: {len(image_base64)} chars...")

            # 构建多模态消息
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self.OCR_PROMPT,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ]

            # 调用 StepFun 多模态模型
            print(f"[OCR] 调用 {self.model} 进行图像识别...")
            llm_start = time.time()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,  # 低温度保证提取准确性
                max_tokens=4096,
            )
            llm_duration = time.time() - llm_start

            extracted_text = response.choices[0].message.content.strip()
            total_duration = time.time() - start_time

            print(f"[OCR] LLM 响应耗时: {llm_duration:.2f}秒")
            print(f"[OCR] 提取完成，文本长度: {len(extracted_text)} 字符")

            # 简单置信度评估
            confidence = self._estimate_confidence(extracted_text)

            return {
                "success": True,
                "text": extracted_text,
                "confidence": confidence,
                "duration": round(total_duration, 2),
            }

        except Exception as e:
            total_duration = time.time() - start_time
            error_msg = str(e)
            print(f"[OCR Error] {error_msg}")
            return {
                "success": False,
                "text": "",
                "confidence": 0,
                "duration": round(total_duration, 2),
                "error": error_msg,
            }

    async def extract_text_from_file_upload(self, file_bytes: bytes, filename: str) -> dict:
        """
        从上传的文件中提取文本（支持图片和 PDF）

        Args:
            file_bytes: 文件二进制内容
            filename: 文件名

        Returns:
            OCR 结果字典
        """
        import mimetypes

        mime_type = mimetypes.guess_type(filename)[0] or "image/jpeg"

        # 判断文件类型
        if mime_type.startswith("image/"):
            # 图片文件 → Base64 + Vision 模型
            image_base64 = base64.b64encode(file_bytes).decode("utf-8")
            return await self.extract_text_from_image(image_base64, mime_type)
        elif mime_type == "application/pdf":
            # PDF 文件 → 使用 file-extract 上传后解析
            return await self._extract_from_pdf(file_bytes, filename)
        else:
            return {
                "success": False,
                "text": "",
                "confidence": 0,
                "duration": 0,
                "error": f"不支持的文件类型: {mime_type}，请上传图片（JPG/PNG）或 PDF 文件",
            }

    async def _extract_from_pdf(self, file_bytes: bytes, filename: str) -> dict:
        """
        从 PDF 文件中提取文本
        使用 StepFun Files API: purpose=file-extract
        """
        start_time = time.time()

        try:
            print(f"[OCR] 上传 PDF 文件: {filename}...")

            # Step 1: 上传文件到 StepFun
            upload_start = time.time()

            # 使用 httpx 直接调用 Files API（避免 openai SDK 兼容性问题）
            import httpx

            upload_url = f"{self.base_url}/files"
            headers = {"Authorization": f"Bearer {self.api_key}"}

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    upload_url,
                    headers=headers,
                    files={"file": (filename, file_bytes, "application/pdf")},
                    data={"purpose": "file-extract"},
                )
                resp.raise_for_status()
                file_data = resp.json()

            file_id = file_data.get("id")
            status = file_data.get("status")
            upload_duration = time.time() - upload_start
            print(f"[OCR] PDF 上传完成 ({upload_duration:.2f}s): file_id={file_id}, status={status}")

            if status != "processed":
                # 等待处理完成
                for _ in range(10):
                    import asyncio
                    await asyncio.sleep(2)
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        check_resp = await client.get(
                            f"{upload_url}/{file_id}",
                            headers=headers,
                        )
                        check_resp.raise_for_status()
                        check_data = check_resp.json()
                        status = check_data.get("status")
                        if status == "processed":
                            break

            # Step 2: 获取文件内容
            async with httpx.AsyncClient(timeout=30.0) as client:
                content_resp = await client.get(
                    f"{upload_url}/{file_id}/content",
                    headers=headers,
                )
                content_resp.raise_for_status()
                extracted_text = content_resp.text

            total_duration = time.time() - start_time
            confidence = self._estimate_confidence(extracted_text)

            print(f"[OCR] PDF 提取完成，文本长度: {len(extracted_text)} 字符，耗时: {total_duration:.2f}s")

            return {
                "success": True,
                "text": extracted_text,
                "confidence": confidence,
                "duration": round(total_duration, 2),
            }

        except Exception as e:
            total_duration = time.time() - start_time
            error_msg = str(e)
            print(f"[OCR PDF Error] {error_msg}")
            return {
                "success": False,
                "text": "",
                "confidence": 0,
                "duration": round(total_duration, 2),
                "error": f"PDF 解析失败: {error_msg}",
            }

    def _estimate_confidence(self, text: str) -> float:
        """
        根据提取结果估算置信度

        评估维度：
        - 文本长度（过短可能是识别失败）
        - 关键医学字段是否包含
        - 是否包含数字（检验指标）
        """
        if not text:
            return 0.0

        score = 0.0

        # 文本长度评估
        length = len(text)
        if length >= 200:
            score += 0.3
        elif length >= 100:
            score += 0.2
        elif length >= 50:
            score += 0.1

        # 关键字段检测
        key_fields = ["诊断", "用药", "出院", "入院", "医嘱", "患者", "姓名", "性别", "年龄"]
        found_fields = sum(1 for field in key_fields if field in text)
        score += min(0.4, found_fields * 0.05)

        # 数字检测（检验指标）
        import re
        numbers = re.findall(r"\d+\.?\d*", text)
        if len(numbers) >= 5:
            score += 0.2
        elif len(numbers) >= 2:
            score += 0.1

        # 医学关键词
        medical_terms = ["血糖", "血压", "mmol", "mg", "mmHg", "糖尿病", "高血压", "口服", "mg"]
        found_terms = sum(1 for term in medical_terms if term in text)
        score += min(0.1, found_terms * 0.02)

        return round(min(1.0, score), 2)
