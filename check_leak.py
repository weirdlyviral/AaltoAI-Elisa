from src import safety, anonymise
import pandas as pd
import numpy as np

df = safety.add_tac(safety.load_raw())
for col in df.select_dtypes(include=[np.number]).columns:
    df[col] = df[col].astype(np.float32)
frame_str = df.astype(str)

for column in frame_str.columns:
    series = frame_str[column]
    for value in series.unique():
        findings = safety._scan_value(value, "test", str(column))
        if findings:
            for f in findings:
                if f.kind == "long_digit_run":
                    print(f"Col {column} value: {value}")
