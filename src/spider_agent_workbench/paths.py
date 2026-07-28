from pathlib import Path
from dotenv import load_dotenv

# src/spider_agent_workbench/paths.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
HF_XLANGAI_SPIDER_DIR = DATA_DIR/ "hf_xlangai_spider"
SPIDER_DIR = DATA_DIR / "spider"
DATABASES_DIR = SPIDER_DIR / "database"
TEST_DATABASES_DIR = SPIDER_DIR / "test_database"
PROMPTS_DIR = PROJECT_ROOT / "src" / "spider_agent_workbench" / "prompts"
LOGS_DIR = PROJECT_ROOT / "logs"

load_dotenv(PROJECT_ROOT / ".env")