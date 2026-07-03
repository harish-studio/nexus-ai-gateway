# app/services/config_loader.py

from pathlib import Path
import yaml
from functools import lru_cache

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "providers.yaml"

@lru_cache(maxsize=1)
def load_providers_config() -> dict:
    """
    Load the provider configuration from the YAML file.
    This function caches the result to avoid reloading the file multiple times.
    """
    with open(_CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    return config

def get_model_rates(provider_name: str, model_name: str) -> tuple[float, float]:
    """
    Get the model rates for a specific provider and model.
    """
    config = load_providers_config()
    
    provider_block = next(
        (p for p in config["providers"] if p["name"] == provider_name), None
    )
    if provider_block is None:
        raise ValueError(f"Unsupported provider: {provider_name}")

    model_block = next(
        (m for m in provider_block["models"] if m["name"] == model_name), None
    )
    if model_block is None:
        raise ValueError(
            f"Unsupported model '{model_name}' for provider '{provider_name}'"
        )

    return model_block["cost_per_1m_input"], model_block["cost_per_1m_output"] 
    return model_rates

