"""
Loads Spider (xlangai/spider) questions from the cached xlsx files and groups
them by db_id. Pure pandas — no LangChain/agent code belongs here.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Iterator, Literal

import pandas as pd

from spider_agent_workbench.paths import HF_XLANGAI_SPIDER_DIR
from spider_agent_workbench.schema import list_databases

Split = Literal["train", "validation"]

_SPLIT_FILES: dict[Split, str] = {
    "train": "train_spider.xlsx",
    "validation": "validation_spider.xlsx",
}


@dataclass(frozen=True)
class SpiderExample:
    db_id: str
    question: str
    gold_sql: str


def load_split(split: Split) -> pd.DataFrame:
    """Load the cached xlsx for a split into a DataFrame."""
    path = HF_XLANGAI_SPIDER_DIR / _SPLIT_FILES[split]
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run scripts/download_hf_dataset_cache.py first."
        )
    return pd.read_excel(path, sheet_name="dataset")


def iter_examples(split: Split) -> Iterator[SpiderExample]:
    """Yield each row of a split as a SpiderExample."""
    df = load_split(split)
    for row in df.itertuples(index=False):
        yield SpiderExample(db_id=row.db_id, question=row.question, gold_sql=row.query)


def group_by_db(examples: list[SpiderExample]) -> dict[str, list[SpiderExample]]:
    """Group examples by db_id, preserving each group's original order."""
    grouped: dict[str, list[SpiderExample]] = {}
    for example in examples:
        grouped.setdefault(example.db_id, []).append(example)
    return grouped


def filter_available(examples: list[SpiderExample]) -> list[SpiderExample]:
    """Drop examples whose db_id has no matching .sqlite file on disk."""
    available = set(list_databases())
    return [example for example in examples if example.db_id in available]
