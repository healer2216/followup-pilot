"""
LLM Gateway - 统一的大语言模型接口
支持 OpenAI / 通义千问(DashScope) / DeepSeek / StepFun 四供应商切换
参考技术设计书 4.1 节
"""
import asyncio
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from app.config import config


class LLMGateway:
    """LLM 网关，提供统一的 chat_completion 接口，支持故障转移"""
    
    # 故障转移优先级（当主提供商失败时自动切换）
    FALLBACK_PROVIDERS = {
        "stepfun": ["openai", "qwen", "deepseek"],
        "openai": ["stepfun", "qwen", "deepseek"],
        "qwen": ["openai", "stepfun", "deepseek"],
        "deepseek": ["openai", "stepfun", "qwen"],
    }
    
    def __init__(self, provider: str = None, api_key: str = None):
        self.provider = provider or config.LLM_PROVIDER
        self.api_key = api_key
        self.client = self._create_client()
        self.model = self._get_model_name()
    
    def _create_client(self) -> AsyncOpenAI:
        """根据配置创建对应的 OpenAI 兼容客户端"""
        key = self.api_key
        if self.provider == "openai":
            api_key = key or config.OPENAI_API_KEY or "sk-dummy-key-for-mock"
            return AsyncOpenAI(
                api_key=api_key,
                base_url=config.OPENAI_BASE_URL
            )
        elif self.provider == "qwen":
            # 通义千问 DashScope 也兼容 OpenAI API
            api_key = key or config.DASHSCOPE_API_KEY or "sk-dummy-key-for-mock"
            return AsyncOpenAI(
                api_key=api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
        elif self.provider == "deepseek":
            api_key = key or config.DEEPSEEK_API_KEY or "sk-dummy-key-for-mock"
            return AsyncOpenAI(
                api_key=api_key,
                base_url=config.DEEPSEEK_BASE_URL
            )
        elif self.provider == "stepfun":
            api_key = key or config.STEPFUN_API_KEY or "sk-dummy-key-for-mock"
            return AsyncOpenAI(
                api_key=api_key,
                base_url=config.STEPFUN_BASE_URL
            )
        else:
            raise ValueError(f"不支持的 LLM 提供商: {self.provider}")
    
    def _get_model_name(self) -> str:
        """获取当前使用的模型名称"""
        if self.provider == "openai":
            return config.OPENAI_MODEL
        elif self.provider == "qwen":
            return config.DASHSCOPE_MODEL
        elif self.provider == "deepseek":
            return config.DEEPSEEK_MODEL
        elif self.provider == "stepfun":
            return config.STEPFUN_MODEL
        else:
            raise ValueError(f"不支持的 LLM 提供商: {self.provider}")
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: Optional[Dict] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        调用 LLM 进行对话
        
        Args:
            messages: 消息列表 [{"role": "user/system/assistant", "content": "..."}]
            temperature: 温度参数 (0-2)，越低越确定
            response_format: 响应格式（如 {"type": "json_object"}）
            max_tokens: 最大输出 token 数
            
        Returns:
            AI 回复文本
        """
        import time
        start_time = time.time()
        
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if response_format:
            kwargs["response_format"] = response_format
        
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        try:
            print(f"[LLM] 调用 {self.provider}/{self.model}...")
            llm_start = time.time()
            response = await self.client.chat.completions.create(**kwargs)
            llm_duration = time.time() - llm_start
            total_duration = time.time() - start_time
            choice = response.choices[0]
            finish_reason = getattr(choice, 'finish_reason', 'unknown')
            content = choice.message.content or ""
            print(f"[LLM] API 响应耗时: {llm_duration:.2f}秒，总耗时: {total_duration:.2f}秒，finish_reason: {finish_reason}，内容长度: {len(content)}")
            if not content:
                print(f"[LLM] 警告: LLM 返回空内容，finish_reason={finish_reason}")
            return content
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {str(e)}")
    
    async def chat_completion_with_retry(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: Optional[Dict] = None,
        max_retries: int = 3,
        max_tokens: Optional[int] = None
    ) -> str:
        """带重试机制的 LLM 调用，支持故障转移"""
        last_error = None
        
        # 先尝试主提供商
        for attempt in range(max_retries):
            try:
                return await self.chat_completion(messages, temperature, response_format, max_tokens)
            except Exception as e:
                last_error = e
                if attempt == max_retries - 1:
                    print(f"[LLM] 主提供商 {self.provider} 失败，尝试故障转移...")
                    break
                print(f"[LLM] 调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(2 ** attempt)  # 指数退避
        
        # 故障转移到备用提供商
        fallback_list = self.FALLBACK_PROVIDERS.get(self.provider, [])
        for fallback_provider in fallback_list:
            try:
                print(f"[LLM] 切换到备用提供商: {fallback_provider}")
                fallback_client = LLMGateway(provider=fallback_provider)
                result = await fallback_client.chat_completion(
                    messages, temperature, response_format, max_tokens
                )
                print(f"[LLM] 故障转移成功: {fallback_provider}")
                return result
            except Exception as e:
                print(f"[LLM] 备用提供商 {fallback_provider} 也失败: {e}")
                last_error = e
                continue
        
        # 所有提供商都失败
        raise RuntimeError(f"所有 LLM 提供商均失败。最后错误: {str(last_error)}")
