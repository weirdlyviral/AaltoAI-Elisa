import pytest
import pandas as pd
import numpy as np
from src import evaluate

def test_a1_group_of_1():
    # A1: a group of 1 subscriber with many rows counts as k=1, not k=rows
    record_df = pd.DataFrame({
        "time_bucket": [1, 1, 1],
        "area": ["A", "A", "A"],
        "radio_access_type": ["4G", "4G", "4G"],
        "application_category": ["Web", "Web", "Web"]
    })
    eval_index = pd.Series(["sub1", "sub1", "sub1"], index=[0,1,2])
    res = evaluate.run_a1(record_df, eval_index, pd.DataFrame())
    assert "in groups < 10" in res["result_record"]

def test_a5_without_noise():
    pass

def test_a6_toy():
    pass

def test_contribution_bounding():
    pass
