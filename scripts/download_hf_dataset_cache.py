
# from datasets import load_dataset

# xlangai_spider_ds = load_dataset("xlangai/spider")
# xlangai_spider_ds.save_to_disk("hf_dataset_cache/spider")

import pandas as pd
from spider_agent_workbench.paths import HF_XLANGAI_SPIDER_DIR

train_dataset_location = HF_XLANGAI_SPIDER_DIR/ "train_spider.xlsx"
validation_dataset_location = HF_XLANGAI_SPIDER_DIR/ "validation_spider.xlsx"

splits = {'train': 'spider/train-00000-of-00001.parquet', 'validation': 'spider/validation-00000-of-00001.parquet'}
train_df = pd.read_parquet("hf://datasets/xlangai/spider/" + splits["train"])
train_df.to_excel(train_dataset_location, sheet_name='dataset', index=False)

validation_df = pd.read_parquet("hf://datasets/xlangai/spider/" + splits["validation"])
validation_df.to_excel(validation_dataset_location, sheet_name='dataset', index=False)
