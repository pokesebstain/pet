"""应用配置加载模块。

使用 `pydantic-settings` 从环境变量 / `.env` 文件读取配置，覆盖数据库、Redis、
云端 LLM 与第三方视觉 API 等外部依赖，并支持按运行环境（dev / test / staging /
prod）切换。

范围约束：模型微调不在本次范围内，因此此处仅包含云端 LLM 与第三方视觉 API 配置，
不含任何本地微调 / vLLM / LoRA 相关配置。

用法::

    from app.core.config import get_settings

    settings = get_settings()
    dsn = settings.database.dsn
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """运行环境枚举。"""

    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


# 各配置分节共享的基础项；显式合并以避免与 env_prefix 冲突。
_COMMON: dict = dict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    case_sensitive=False,
)


class _Section(BaseSettings):
    """带公共配置的分节基类：支持 `.env`、环境变量前缀、忽略额外字段。"""

    model_config = SettingsConfigDict(**_COMMON)


class DatabaseSettings(_Section):
    """PostgreSQL（含 pgvector / TimescaleDB 扩展）连接配置。"""

    model_config = SettingsConfigDict(env_prefix="PETOPS_DB_", **_COMMON)

    host: str = "localhost"
    port: int = 5432
    user: str = "petops"
    password: SecretStr = SecretStr("petops")
    name: str = "petops"
    # 连接池
    pool_size: int = 10
    max_overflow: int = 20

    @field_validator("port")
    @classmethod
    def _valid_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("端口号必须在 1..65535 之间")
        return v

    @property
    def dsn(self) -> str:
        """返回 SQLAlchemy / psycopg 可用的连接串。"""
        pwd = self.password.get_secret_value()
        return f"postgresql+psycopg://{self.user}:{pwd}@{self.host}:{self.port}/{self.name}"


class RedisSettings(_Section):
    """Redis 缓存 / 事件总线（Redis Stream）配置。"""

    model_config = SettingsConfigDict(env_prefix="PETOPS_REDIS_", **_COMMON)

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None

    @property
    def url(self) -> str:
        auth = ""
        if self.password is not None:
            auth = f":{self.password.get_secret_value()}@"
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class LLMSettings(_Section):
    """云端 LLM（通义千问 / 智谱 GLM）配置。

    仅覆盖云端提示工程 / 少样本调用；不含任何本地微调模型配置。
    """

    model_config = SettingsConfigDict(env_prefix="PETOPS_LLM_", **_COMMON)

    provider: str = "qwen"  # qwen / glm
    api_key: SecretStr | None = None
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    timeout_seconds: float = 10.0
    max_retries: int = 3

    @field_validator("timeout_seconds")
    @classmethod
    def _positive_timeout(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("LLM 超时时间必须大于 0")
        return v


class VisionSettings(_Section):
    """第三方视觉健康检测 API（宠智灵 / 百目魔君）配置。

    范围约束：视觉能力仅经第三方 API 实现，不含自研 / 微调视觉模型配置。
    """

    model_config = SettingsConfigDict(env_prefix="PETOPS_VISION_", **_COMMON)

    provider: str = "chongzhiling"  # chongzhiling / baimu
    api_key: SecretStr | None = None
    base_url: str = "https://api.example-vision.com/v1"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    max_image_mb: int = 10


class WeComSettings(_Section):
    """企业微信（WeCom）回调接入配置（Requirement 21）。

    对应企业微信管理后台"接收消息服务器配置"中的 Token / EncodingAESKey，以及企业
    ``corp_id``；出站主动推送可选配置 ``secret``（应用 Secret）。

    安全：``token`` / ``encoding_aes_key`` / ``secret`` 一律以 :class:`~pydantic.SecretStr`
    承载，避免在日志 / repr 中泄露。提供**安全空默认值**，使未配置企业微信时应用仍可正常
    构造与启动（仅 ``/wecom/callback`` 路由在未配置时返回 503）。
    """

    model_config = SettingsConfigDict(env_prefix="PETOPS_WECOM_", **_COMMON)

    #: 企业微信企业 ID（CorpID）；解密后校验 ReceiveId 是否等于该值。
    corp_id: str = ""
    #: 回调 Token，用于消息签名校验。
    token: SecretStr = SecretStr("")
    #: EncodingAESKey（43 位），Base64 解码后得到 32 字节 AES-256 密钥。
    encoding_aes_key: SecretStr = SecretStr("")
    #: 可选：应用 Secret，用于出站主动推送（获取 access_token）。
    secret: SecretStr = SecretStr("")
    #: 企业微信服务端 API 根地址（出站获取 access_token / 发送消息）。
    api_base_url: str = "https://qyapi.weixin.qq.com"
    #: 可选：应用 AgentId，用于应用消息 ``/cgi-bin/message/send`` 主动推送。
    agent_id: int | None = None

    @property
    def is_configured(self) -> bool:
        """是否已提供最小可用的回调配置（corp_id + token + encoding_aes_key）。"""
        return bool(
            self.corp_id.strip()
            and self.token.get_secret_value().strip()
            and self.encoding_aes_key.get_secret_value().strip()
        )

    @property
    def is_outbound_configured(self) -> bool:
        """是否已提供出站主动推送所需配置（在入站配置基础上 + secret + agent_id）。"""
        return bool(
            self.is_configured
            and self.secret.get_secret_value().strip()
            and self.agent_id is not None
        )


class Settings(_Section):
    """顶层应用配置，聚合各子配置分节。"""

    model_config = SettingsConfigDict(env_prefix="PETOPS_", **_COMMON)

    environment: Environment = Environment.DEV
    debug: bool = False

    #: 单门店默认租户标识（Requirement 5 / 设计 14.1）。留空时回退到企业微信 ``corp_id``，
    #: 从而使"运行时租户 == corp_id"（企业微信编解码器的默认映射）与种子数据保持一致。
    default_tenant_id: str = ""

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    wecom: WeComSettings = Field(default_factory=WeComSettings)

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PROD

    @property
    def resolved_default_tenant_id(self) -> str:
        """返回生效的默认租户：显式配置优先，否则回退企业微信 ``corp_id``。

        单门店自建应用场景下，企业微信编解码器把所有回调映射到
        ``default_tenant_id``（缺省即 ``corp_id``），因此种子数据与运行时租户须一致。
        两者皆空时返回空串（未配置，调用方据此跳过 DB 接线 / 种子）。
        """
        explicit = (self.default_tenant_id or "").strip()
        if explicit:
            return explicit
        return (self.wecom.corp_id or "").strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回进程内缓存的配置单例。

    通过 `lru_cache` 保证同一进程内仅加载一次；测试中可调用
    ``get_settings.cache_clear()`` 后重新加载以切换环境。
    """
    return Settings()
