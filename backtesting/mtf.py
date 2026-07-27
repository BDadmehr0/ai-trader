import pandas as pd


def prepare_mtf_data(
    df_15m,
    df_1h,
    df_4h,
):

    df_15m = df_15m.copy()
    df_1h = df_1h.copy()
    df_4h = df_4h.copy()

    # --------------------------------
    # IMPORTANT
    # Remove current incomplete candle
    # --------------------------------

    df_15m = df_15m.iloc[:-1].copy()

    df_1h = df_1h.iloc[:-1].copy()

    df_4h = df_4h.iloc[:-1].copy()

    # --------------------------------
    # Sort
    # --------------------------------

    df_15m = df_15m.sort_values(
        "timestamp"
    )

    df_1h = df_1h.sort_values(
        "timestamp"
    )

    df_4h = df_4h.sort_values(
        "timestamp"
    )

    # --------------------------------
    # Rename higher TF columns
    # --------------------------------

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

    # --------------------------------
    # Merge 1H
    # --------------------------------

    merged = pd.merge_asof(
        df_15m,
        df_1h,
        on="timestamp",
        direction="backward",
    )

    # --------------------------------
    # Merge 4H
    # --------------------------------

    merged = pd.merge_asof(
        merged,
        df_4h,
        on="timestamp",
        direction="backward",
    )

    # --------------------------------
    # Remove missing
    # --------------------------------

    merged = merged.dropna()

    return merged.reset_index(
        drop=True
    )