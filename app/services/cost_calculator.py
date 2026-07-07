# app/services/cost_calculator.py

from app.providers.anthropic_provider import ANTHROPIC_CONFIG
from app.providers.ollama_provider import OLLAMA_CONFIG
from app.providers.openai_provider import OPENAI_CONFIG
from app.services.config_loader import get_model_rates 

_PROVIDER_CONFIGS = {
    "openai": OPENAI_CONFIG,
    "anthropic": ANTHROPIC_CONFIG,
    "ollama_chat": OLLAMA_CONFIG,
}

class CostCalculator:       
    
    def compute(
        self, provider_name: str, model_name: str, input_tokens: int, output_tokens: int
    ) -> float:
        """
        Compute the cost of a request based on the specific model used.
        Rates are sourced from config/providers.yaml (single source of truth),
        not hardcoded in provider modules.
        """
        cost_per_1m_input, cost_per_1m_output = get_model_rates(provider_name, model_name)

        input_cost = (input_tokens / 1_000_000) * cost_per_1m_input
        output_cost = (output_tokens / 1_000_000) * cost_per_1m_output

        return round(input_cost + output_cost, 6)


