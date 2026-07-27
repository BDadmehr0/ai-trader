import pandas as pd


def prepare_mtf_data(
    df_15m,
    df_1h,
    df_4h,
):

    df_15m = df_15m.copy()

    df_1h = df_1h.copy()

    df_4h = df_4h.copy()

    df_15m = df_15m.sort_values(
        "timestamp"
    )

    df_1h = df_1h.sort_values(
        "timestamp"
    )

    df_4h = df_4h.sort_values(
        "timestamp"
    )

    df_1h = df_1h.rename(
        columns={
            column: f"{column}_1h"
            for column in df_1h.columns
            if column != "timestamp"
        }
    )

    df_4h = df_4h.rename(
        columns={
            column: f"{column}_4h"
            for column in df_4h.columns
            if column != "timestamp"
        }
    )

    merged = pd.merge_asof(
        df_15m,
        df_1h,
        on="timestamp",
        direction="backward",
    )

    merged = pd.merge_asof(
        merged,
        df_4h,
        on="timestamp",
        direction="backward",
    )

    merged = merged.dropna()

    return merged.reset_index(
        drop=True
    )