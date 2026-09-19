"""Which columns would trip the leak guard after rounding floats to 5 decimals?

Diagnostic only. Reports column names and finding counts - never values.
"""

from collections import Counter

import pandas as pd

from src import safety


@safety.safe_main
def main() -> None:
    df = safety.add_tac(safety.load_raw())
    for col in df.columns:
        if pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].round(5)

    counts: Counter[tuple[str, str]] = Counter()
    frame_str = df.astype(str)
    for column in frame_str.columns:
        for value in frame_str[column].unique():
            for finding in safety.check_text(value, "round5"):
                counts[(str(column), finding.kind)] += 1

    if not counts:
        print("round(5): CLEAN - no findings in any column.")
        return
    print(f"{'column':<40} {'kind':<16} distinct values affected")
    for (column, kind), n in counts.most_common():
        print(f"{column:<40} {kind:<16} {n}")


if __name__ == "__main__":
    main()
