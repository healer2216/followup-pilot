"""
应用配置管理
从环境变量读取配置，提供默认值
"""
import os
from dotenv import load_dotenv
from typing import Optional

# 加载 .env 文件
load_dotenv()


class Config:
    """全局配置"""
    
    # LLM 配置
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    DASHSCOPE_API_KEY: Optional[str] = os.getenv("DASHSCOPE_API_KEY")
    DASHSCOPE_MODEL: str = os.getenv("DASHSCOPE_MODEL", "qwen-max")
    
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    
    # StepFun API
    STEPFUN_API_KEY: Optional[str] = os.getenv("STEPFUN_API_KEY")
    STEPFUN_BASE_URL: str = os.getenv("STEPFUN_BASE_URL", "https://api.stepfun.com/step_plan/v1")
    STEPFUN_MODEL: str = os.getenv("STEPFUN_MODEL", "step-3.7-flash")
    
    # KnowS API 配置
    KNOWS_BASE_URL: str = os.getenv("KNOWS_BASE_URL", "https://api.nullht.com/v1")
    KNOWS_RATE_LIMIT_DELAY: float = float(os.getenv("KNOWS_RATE_LIMIT_DELAY", "0.4"))
    
    # 应用配置
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    
    # 会话存储路径
    SESSION_DIR: str = os.getenv("SESSION_DIR", "data/sessions")
    
    @classmethod
    def validate(cls):
        """验证必需的配置项"""
        if cls.LLM_PROVIDER == "openai" and not cls.OPENAI_API_KEY:
            raise ValueError("使用 OpenAI 时需要设置 OPENAI_API_KEY")
        elif cls.LLM_PROVIDER == "qwen" and not cls.DASHSCOPE_API_KEY:
            raise ValueError("使用通义千问时需要设置 DASHSCOPE_API_KEY")
        elif cls.LLM_PROVIDER == "deepseek" and not cls.DEEPSEEK_API_KEY:
            raise ValueError("使用 DeepSeek 时需要设置 DEEPSEEK_API_KEY")


# 导出单例配置实例
config = Config()
settings = config
