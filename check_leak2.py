from src import safety
import pandas as pd

df = safety.add_tac(safety.load_raw())
for col in df.columns:
    if pd.api.types.is_float_dtype(df[col]):
        df[col] = df[col].round(5)

frame_str = df.astype(str)
findings = []
for column in frame_str.columns:
    series = frame_str[column]
    for value in series.unique():
        f = safety._scan_value(value, "test", str(column))
        if f:
            for x in f:
                if x.kind == "long_digit_run":
                    print(f"Col {column} value: {value}")
