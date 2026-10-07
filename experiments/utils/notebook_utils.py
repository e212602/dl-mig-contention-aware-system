import json
from datetime import datetime
from io import StringIO
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Publication-style defaults
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "savefig.dpi": 300,
    "pdf.fonttype": 42,   # embeds TrueType fonts (journal-friendly)
    "ps.fonttype": 42,
})


def get_latest_experiment_dir(
    base_dir: str | Path,
    exp_path_pre: str,
    key: str = "",
    value: object = "",
) -> Path | None:
    """
    Finds and returns the latest directory matching `exp_path_pre`.

    When both `key` and `value` are provided, only directories whose
    `run_metadata.json` contains that exact top-level key/value pair are
    considered.

    Expected suffix format: YYYYMMDDTHHMMSS
    (e.g., 20260930T004307)

    :param base_dir: The directory containing all the experiment folders.
    :param exp_path_pre: The prefix matching the experiment name and settings.
    :param key: Optional top-level key to match in `run_metadata.json`.
    :param value: Optional value that `key` must match in `run_metadata.json`.
    :return: Latest matching experiment directory, or None if none is found.
    """
    base_path = Path(base_dir)

    # Match directories starting with the prefix and ending with a timestamp.
    # e.g., "ram_bandwidth_stress_1v1_cpuoffload-on_*"
    matching_dirs = [
        p for p in base_path.glob(f"{exp_path_pre}_*") if p.is_dir()
    ]

    if key and value != "":
        metadata_matching_dirs = []
        for directory in matching_dirs:
            metadata_path = directory / "run_metadata.json"
            if not metadata_path.is_file():
                continue
            with metadata_path.open(encoding="utf-8") as metadata_file:
                metadata = json.load(metadata_file)
            if (
                isinstance(metadata, dict)
                and key in metadata["parameters"]
                and metadata["parameters"][key] == value
            ):
                metadata_matching_dirs.append(directory)
        matching_dirs = metadata_matching_dirs

    if not matching_dirs:
        return None

    def extract_timestamp(dir_path: Path) -> datetime:
        # Extract the string following the last underscore
        timestamp_str = dir_path.name.rsplit('_', 1)[-1]
        try:
            return datetime.strptime(timestamp_str, "%Y%m%dT%H%M%S")
        except ValueError:
            # Fall back to minimum datetime if a folder doesn't match the timestamp format
            return datetime.min

    latest_dir = max(matching_dirs, key=extract_timestamp)

    # Check if a valid timestamp was found
    if extract_timestamp(latest_dir) == datetime.min:
        return None

    return latest_dir


def read_summary_report(file):
    with open(file, "r") as f:
        text = f.read()

    # Headers that identify each table
    headers = [
        "Metric,avg,min,max,sum,p1,p5,p10,p25,p50,p75,p90,p95,p99,std",
        "Metric,Value",
        "Endpoint,GPU_Index,GPU_Name,GPU_UUID,Platform,Metric,avg,min,max,sum,p1,p5,p10,p25,p50,p75,p90,p95,p99,std"
    ]

    # Find the starting position of each table
    positions = [text.find(header) for header in headers]

    # Extract each table
    parts = []

    for i, start in enumerate(positions):
        if start == -1:
            continue

        if i + 1 < len(positions) and positions[i + 1] != -1:
            end = positions[i + 1]
        else:
            end = len(text)

        parts.append(text[start:end].strip())

    # Convert to DataFrames
    # df_metrics = pd.read_csv(StringIO(parts[0]))
    df_summary = pd.read_csv(StringIO(parts[1]))
    # df_gpu = pd.read_csv(StringIO(parts[2])) 
    return df_summary


def _grouped_bar(ax, results_df, models, phases, column, ylabel,
                 colors=None, hatches=None, annotate=True, fmt="{:.0f}"):
    n_phases = len(phases)
    x = np.arange(len(models))
    total_width = 0.8
    width = total_width / n_phases

    if colors is None:
        cmap = plt.get_cmap("tab10") if n_phases <= 10 else plt.get_cmap("tab20")
        colors = [cmap(i) for i in range(n_phases)]
    if hatches is None:
        # hatches keep the plot readable in grayscale print
        hatches = ["", "//", "..", "xx", "\\\\", "--", "++", "oo"]

    for i, phase in enumerate(phases):
        data = (
            results_df[results_df["Mode"] == phase]
            .set_index("Model")
            .reindex(models)
        )
        offset = (i - (n_phases - 1) / 2) * width
        bars = ax.bar(
            x + offset,
            data[column].values,
            width,
            label=phase,
            color=colors[i],
            edgecolor="black",
            linewidth=0.6,
            hatch=hatches[i % len(hatches)],
            zorder=3,
        )
        if annotate:
            ax.bar_label(bars, labels=[
                fmt.format(v) if np.isfinite(v) else "" for v in data[column].values
            ], padding=2, fontsize=8, rotation=90 if n_phases > 2 else 0)

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right")
    ax.set_xlabel("Model")
    ax.set_ylabel(ylabel)
    ax.yaxis.grid(True, linestyle="--", linewidth=0.5, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)
    ax.margins(y=0.15)  # headroom for value labels
    ax.legend(title="Phase", frameon=False)


def plot_throughput_and_rps(MODEL_LIST, results_df, exp_phases, save_prefix=None):
    models = list(MODEL_LIST)
    phases = list(exp_phases)

    specs = [
        ("Request Throughput", "Request Throughput (requests/sec)", "{:.0f}", "request_throughput"),
        ("Output Token Throughput", "Output Token Throughput (tokens/s)", "{:.1f}", "output_throughput"),
    ]

    for column, ylabel, fmt, name in specs:
        fig, ax = plt.subplots(figsize=(8, 6))
        _grouped_bar(ax, results_df, models, phases, column, ylabel, fmt=fmt)
        fig.tight_layout()
        if save_prefix:
            fig.savefig(f"../figures/{save_prefix}_{name}.pdf", bbox_inches="tight")
            fig.savefig(f"../figures/{save_prefix}_{name}.png", bbox_inches="tight")
        plt.show()