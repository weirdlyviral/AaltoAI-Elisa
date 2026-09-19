"""Which columns would trip the leak guard if cast to float32?

Diagnostic only. Reports column names and finding counts - never values, which
is why it does not print the offending cells.
"""

from collections import Counter

import numpy as np

from src import safety


@safety.safe_main
def main() -> None:
    df = safety.add_tac(safety.load_raw())
    for col in df.select_dtypes(include=[np.number]).columns:
        df[col] = df[col].astype(np.float32)

    counts: Counter[tuple[str, str]] = Counter()
    frame_str = df.astype(str)
    for column in frame_str.columns:
        for value in frame_str[column].unique():
            for finding in safety.check_text(value, "float32_cast"):
                counts[(str(column), finding.kind)] += 1

    if not counts:
        print("float32 cast: CLEAN - no findings in any column.")
        return
    print(f"{'column':<40} {'kind':<16} distinct values affected")
    for (column, kind), n in counts.most_common():
        print(f"{column:<40} {kind:<16} {n}")


if __name__ == "__main__":
    main()
