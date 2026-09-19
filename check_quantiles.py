"""Quantiles of a sparse volume column. Aggregates only."""

from src import safety


@safety.safe_main
def main() -> None:
    df = safety.load_raw()
    col = "im_video_GB_sum"
    if col not in df.columns:
        print(f"{col} not present")
        return
    print(f"Overall p99 : {df[col].quantile(0.99)}")
    nz = df[df[col] > 0][col]
    print(f"Non-zero n  : {len(nz)}")
    print(f"Non-zero p99: {nz.quantile(0.99)}")
    print(f"Non-zero p50: {nz.quantile(0.50)}")


if __name__ == "__main__":
    main()
