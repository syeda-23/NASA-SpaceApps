from pathlib import Path
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


INPUT_FILE = Path(
    "data/raw/doseE_sol_filter_update.txt"
)

PROCESSED_DIR = Path(
    "data/processed"
)

OUTPUT_DIR = Path(
    "outputs"
)

PROCESSED_DIR.mkdir(
    parents=True,
    exist_ok=True
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

OUTPUT_JSON = (
    PROCESSED_DIR
    / "radiation_scenarios.json"
)

OUTPUT_CSV = (
    PROCESSED_DIR
    / "glen_torridon_rad_measurements.csv"
)

OUTPUT_PLOT = (
    OUTPUT_DIR
    / "glen_torridon_rad.png"
)

SOL_START = 2300
SOL_END = 3072


def load_rad_data(path):

    raw = pd.read_csv(
        path,
        sep=r"\s+",
        comment="#",
        header=None,
        engine="python",
    )

    raw = raw.dropna(
        axis=1,
        how="all"
    )

    print("\nRAW DATA")
    print("Shape:", raw.shape)

    print("\nFirst rows:")
    print(
        raw.head(10).to_string()
    )

    numeric = raw.apply(
        pd.to_numeric,
        errors="coerce"
    )

    print("\nNUMERIC COLUMN RANGES")

    for column in numeric.columns:

        values = (
            numeric[column]
            .dropna()
        )

        if values.empty:
            continue

        print(
            "Column",
            column,
            "| min:",
            values.min(),
            "| max:",
            values.max(),
            "| median:",
            values.median()
        )

    sol_column = None

    best_sol_matches = 0

    for column in numeric.columns:

        values = (
            numeric[column]
            .dropna()
        )

        if values.empty:
            continue

        matches = (
            (values >= SOL_START)
            & (values <= SOL_END)
        ).sum()

        if matches > best_sol_matches:

            best_sol_matches = matches
            sol_column = column

    if (
        sol_column is None
        or best_sol_matches == 0
    ):

        raise ValueError(
            "Could not identify the Martian "
            "sol column in the RAD dataset."
        )

    print(
        "\nDetected SOL column:",
        sol_column
    )

    print(
        "Rows in Glen Torridon sol range:",
        best_sol_matches
    )

    dose_candidates = []

    for column in numeric.columns:

        if column == sol_column:
            continue

        values = (
            numeric[column]
            .dropna()
        )

        if values.empty:
            continue

        positive_fraction = (
            values >= 0
        ).mean()

        median = (
            values.median()
        )

        if (
            positive_fraction > 0.80
            and median > 0
            and median < 10000
        ):

            dose_candidates.append(
                column
            )

    dose_candidates = [
        column
        for column in dose_candidates
        if column > sol_column
    ]

    print(
        "Possible dose columns:",
        dose_candidates
    )

    if len(dose_candidates) < 2:

        raise ValueError(
            "Could not confidently detect both "
            "the original and filtered RAD "
            "dose-rate columns."
        )

    dose_original_column = (
        dose_candidates[-2]
    )

    dose_filtered_column = (
        dose_candidates[-1]
    )

    print(
        "Original dose column:",
        dose_original_column
    )

    print(
        "Filtered dose column:",
        dose_filtered_column
    )

    data = pd.DataFrame(
        {
            "sol":
                numeric[
                    sol_column
                ],

            "dose_original_ugy_day":
                numeric[
                    dose_original_column
                ],

            "dose_filtered_ugy_day":
                numeric[
                    dose_filtered_column
                ],
        }
    )

    data = data.replace(
        [np.inf, -np.inf],
        np.nan
    )

    data = data.dropna(
        subset=[
            "sol",
            "dose_original_ugy_day",
        ]
    )

    data = data[
        data[
            "dose_original_ugy_day"
        ] >= 0
    ].copy()

    data["sol"] = (
        data["sol"]
        .round()
        .astype(int)
    )

    print("\nDetected overall sol range:")

    print(
        data["sol"].min(),
        "to",
        data["sol"].max()
    )

    print("\nDose-rate statistics:")

    print(
        data[
            "dose_original_ugy_day"
        ].describe()
    )

    return data


def filter_glen_torridon(
    data
):

    campaign = data[
        (
            data["sol"]
            >= SOL_START
        )
        &
        (
            data["sol"]
            <= SOL_END
        )
    ].copy()

    print(
        "\nMeasurements found between",
        SOL_START,
        "and",
        SOL_END,
        ":",
        len(campaign)
    )

    if campaign.empty:

        raise ValueError(
            "No measurements were found "
            "during the selected campaign period."
        )

    print("\nFirst campaign measurements:")

    print(
        campaign.head(
            10
        ).to_string(
            index=False
        )
    )

    return campaign


def calculate_scenarios(
    campaign
):

    dose = (
        campaign[
            "dose_original_ugy_day"
        ]
        .dropna()
        .to_numpy(
            dtype=float
        )
    )

    if dose.size == 0:

        raise ValueError(
            "No valid dose values remain "
            "after cleaning."
        )

    scenarios = {

        "low":
            float(
                np.percentile(
                    dose,
                    25
                )
            ),

        "nominal":
            float(
                np.median(
                    dose
                )
            ),

        "elevated":
            float(
                np.percentile(
                    dose,
                    90
                )
            ),

        "minimum":
            float(
                np.min(
                    dose
                )
            ),

        "maximum":
            float(
                np.max(
                    dose
                )
            ),

        "mean":
            float(
                np.mean(
                    dose
                )
            ),

        "standard_deviation":
            float(
                np.std(
                    dose
                )
            ),

        "measurement_count":
            int(
                dose.size
            ),
    }

    return scenarios


def create_plot(
    campaign,
    scenarios
):

    figure, axis = (
        plt.subplots(
            figsize=(12, 5)
        )
    )

    axis.plot(

        campaign["sol"],

        campaign[
            "dose_original_ugy_day"
        ],

        color="lightgray",

        linewidth=0.6,

        label=(
            "Measured dose rate"
        ),
    )

    if (
        campaign[
            "dose_filtered_ugy_day"
        ]
        .notna()
        .any()
    ):

        axis.plot(

            campaign["sol"],

            campaign[
                "dose_filtered_ugy_day"
            ],

            color="navy",

            linewidth=1.0,

            label=(
                "Filtered dose rate"
            ),
        )

    axis.axhline(

        scenarios[
            "nominal"
        ],

        color="green",

        linestyle="--",

        linewidth=1.2,

        label=(
            "Nominal scenario"
        ),
    )

    axis.axhline(

        scenarios[
            "elevated"
        ],

        color="red",

        linestyle="--",

        linewidth=1.2,

        label=(
            "Elevated scenario"
        ),
    )

    axis.set_title(
        "Curiosity RAD during the "
        "Glen Torridon campaign"
    )

    axis.set_xlabel(
        "Curiosity mission sol"
    )

    axis.set_ylabel(
        "RAD E-detector dose rate "
        "(µGy/day)"
    )

    axis.legend()

    axis.grid(
        alpha=0.2
    )

    figure.tight_layout()

    figure.savefig(
        OUTPUT_PLOT,
        dpi=200
    )

    plt.close(
        figure
    )


def save_results(
    campaign,
    scenarios
):

    campaign.to_csv(
        OUTPUT_CSV,
        index=False
    )

    output = {

        "source":
            (
                "MSL Curiosity RAD "
                "E-detector dose-rate dataset"
            ),

        "campaign":
            (
                "Glen Torridon campaign period"
            ),

        "sol_start":
            SOL_START,

        "sol_end":
            SOL_END,

        "dose_rate_unit":
            "microgray/day",

        "spatial_raster":
            False,

        "scenarios":
            scenarios,

        "interpretation":
            (
                "Historical Curiosity RAD "
                "measurements used to create "
                "route-planning radiation "
                "scenarios. These measurements "
                "do not represent an exact "
                "future radiation forecast."
            ),
    }

    with OUTPUT_JSON.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=4
        )


def print_scenarios(
    scenarios
):

    print(
        "\n=============================="
    )

    print(
        "RADIATION SCENARIOS"
    )

    print(
        "=============================="
    )

    print(
        "Low:"
    )

    print(
        scenarios["low"],
        "µGy/day"
    )

    print(
        "\nNominal:"
    )

    print(
        scenarios["nominal"],
        "µGy/day"
    )

    print(
        "\nElevated:"
    )

    print(
        scenarios["elevated"],
        "µGy/day"
    )

    print(
        "\nMinimum observed:"
    )

    print(
        scenarios["minimum"],
        "µGy/day"
    )

    print(
        "\nMaximum observed:"
    )

    print(
        scenarios["maximum"],
        "µGy/day"
    )

    print(
        "\nMean:"
    )

    print(
        scenarios["mean"],
        "µGy/day"
    )

    print(
        "\nMeasurements:"
    )

    print(
        scenarios[
            "measurement_count"
        ]
    )


def main():

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            "\nRAD dataset is missing:\n"
            f"{INPUT_FILE}\n"
        )

    print(
        "Reading:"
    )

    print(
        INPUT_FILE.resolve()
    )

    data = load_rad_data(
        INPUT_FILE
    )

    campaign = filter_glen_torridon(
        data
    )

    scenarios = calculate_scenarios(
        campaign
    )

    save_results(
        campaign,
        scenarios
    )

    create_plot(
        campaign,
        scenarios
    )

    print_scenarios(
        scenarios
    )

    print(
        "\n=============================="
    )

    print(
        "PROCESSING COMPLETE"
    )

    print(
        "=============================="
    )

    print(
        "\nA* INPUT:"
    )

    print(
        OUTPUT_JSON
    )

    print(
        "\nCleaned measurements:"
    )

    print(
        OUTPUT_CSV
    )

    print(
        "\nPlot:"
    )

    print(
        OUTPUT_PLOT
    )


if __name__ == "__main__":
    main()