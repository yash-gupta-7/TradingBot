"""Load the project's single YAML config file."""
from pathlib import Path
import yaml


def load_config(path: str = "config/config.yaml") -> dict:
    with open(Path(path), "r") as f:
        return yaml.safe_load(f)
