"""Конфигурация AI-сервиса из переменных окружения. Секреты не логируются."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


# Приложение 3 кейса: только эти модели разрешены. Сравнение по нормализованному имени,
# чтобы принять вариант с префиксом провайдера (например, "zai-org/GLM-5.3-Flash").
ALLOWED_MODELS = {
    'gemma-4-26b-a4b': 'Gemma 4 26B A4B',
    'glm-5.3-flash': 'GLM-5.3-Flash',
    'qwen3.6-35b-a3b': 'Qwen3.6 35B A3B',
    'deepseek-v4.1-flash': 'DeepSeek-V4.1-Flash',
    'qwen3-vl-30b-a3b-instruct': 'Qwen3-VL-30B-A3B-Instruct',
    'kimi-k2.6': 'Kimi-K2.6',
}


def normalize_model(name: str) -> str:
    base = name.strip().split('/')[-1].lower().replace(' ', '-').replace('_', '-')
    return base


def is_allowed_model(name: str) -> bool:
    n = normalize_model(name)
    return any(n == k or n.startswith(k + '-') or n.startswith(k + ':') for k in ALLOWED_MODELS)


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env('DATABASE_URL'))
    data_dir: Path = field(default_factory=lambda: Path(_env('DATA_DIR', str(Path(__file__).resolve().parents[2] / 'data'))))
    state_dir: Path = field(default_factory=lambda: Path(_env('STATE_DIR', '/tmp/ai-state')))
    raw_dir: str = field(default_factory=lambda: _env('RAW_DATA_DIR'))
    min_revenue: float = field(default_factory=lambda: float(_env('SEGMENT_MIN_REVENUE', '5000000000')))

    llm_base_url: str = field(default_factory=lambda: _env('LLM_BASE_URL').rstrip('/'))
    llm_api_key: str = field(default_factory=lambda: _env('LLM_API_KEY'))
    model_planner: str = field(default_factory=lambda: _env('LLM_MODEL_PLANNER', 'z-ai/glm-5.3-flash'))
    model_extractor: str = field(default_factory=lambda: _env('LLM_MODEL_EXTRACTOR', 'google/gemma-4-26b-a4b-it'))
    model_writer: str = field(default_factory=lambda: _env('LLM_MODEL_WRITER', 'qwen/qwen3.6-35b-a3b'))
    model_chat: str = field(default_factory=lambda: _env('LLM_MODEL_CHAT', 'qwen/qwen3.6-35b-a3b'))
    llm_timeout_s: int = field(default_factory=lambda: _int('LLM_TIMEOUT_SECONDS', 60))
    llm_daily_token_budget: int = field(default_factory=lambda: _int('LLM_DAILY_TOKEN_BUDGET', 1_500_000))
    llm_reasoning: bool = field(default_factory=lambda: _env('LLM_REASONING', 'off').lower() in ('1', 'on', 'true'))
    llm_max_tokens: int = field(default_factory=lambda: _int('LLM_MAX_TOKENS', 2200))

    include_edge_cases: bool = field(default_factory=lambda: _env('INCLUDE_EDGE_CASES', 'on').lower() in ('1', 'on', 'true'))
    agent_max_steps: int = field(default_factory=lambda: _int('AGENT_MAX_STEPS', 12))
    agent_max_seconds: int = field(default_factory=lambda: _int('AGENT_MAX_SECONDS', 150))
    agent_max_repairs: int = field(default_factory=lambda: _int('AGENT_MAX_REPAIRS', 1))
    feed_window_days: int = field(default_factory=lambda: _int('FEED_WINDOW_DAYS', 45))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    def public(self) -> dict:
        """Безопасное описание конфигурации для /health и README — без ключей."""
        return {
            'llm_enabled': self.llm_enabled,
            'llm_base_url_set': bool(self.llm_base_url),
            'models': {
                'planner': self.model_planner, 'extractor': self.model_extractor,
                'writer': self.model_writer, 'chat': self.model_chat,
            },
            'models_allowed': {k: is_allowed_model(v) for k, v in {
                'planner': self.model_planner, 'extractor': self.model_extractor,
                'writer': self.model_writer, 'chat': self.model_chat}.items()},
            'daily_token_budget': self.llm_daily_token_budget,
            'agent_limits': {'max_steps': self.agent_max_steps, 'max_seconds': self.agent_max_seconds,
                             'max_repairs': self.agent_max_repairs},
        }


settings = Settings()
