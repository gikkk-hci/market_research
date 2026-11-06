"""Read the shared .env without printing credentials or changing process variables."""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def env_values():
    for path in (PROJECT_ROOT.parent / ".env", PROJECT_ROOT / ".env"):
        if not path.is_file():
            continue
        values = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.removeprefix("export ").split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name.strip()] = value
        return values
    return {}


def load_data_key():
    from cloud_apps.config import secret
    cloud_key = secret("DATA_GO_KR_KEY")
    if cloud_key:
        return cloud_key
    key = os.environ.get("DATA_GO_KR_KEY", "") or env_values().get("DATA_GO_KR_KEY", "")
    if key:
        return key
    path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if path.is_file():
        import tomllib
        return str(tomllib.loads(path.read_text(encoding="utf-8-sig")).get("DATA_GO_KR_KEY", ""))
    return ""
