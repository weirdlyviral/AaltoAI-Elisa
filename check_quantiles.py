from src import safety
import pandas as pd
df = safety.load_raw()
col = 'im_video_GB_sum'
if col in df.columns:
    print(f"Overall p99: {df[col].quantile(0.99)}")
    nz = df[df[col] > 0][col]
    print(f"Non-zero count: {len(nz)}")
    print(f"Non-zero p99: {nz.quantile(0.99)}")
    print(f"Non-zero p50: {nz.quantile(0.50)}")
