"""Exploratory figures for a dataset profile (see profiling.py).

Kept separate from profiling itself: profiling produces plain-data dicts that
get written to JSON regardless of whether matplotlib is even installed, and
this module turns that data into PNGs. Matplotlib is used with the non-GUI
"Agg" backend since this always runs headless.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def _bar(ax, labels: list[str], values: list[float], title: str, xlabel: str = "") -> None:
    ax.barh(labels, values, color="#4C72B0")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.invert_yaxis()


def plot_events_by_type(profile: dict[str, Any], out_path: Path) -> None:
    items = sorted(profile["events_by_type"].items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(8, max(3, len(labels) * 0.35)))
    _bar(ax, labels, values, f"{profile['dataset']}: events by type", "event count")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_events_by_layer(profile: dict[str, Any], out_path: Path) -> None:
    items = sorted(profile["events_by_layer"].items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(6, 3))
    _bar(ax, labels, values, f"{profile['dataset']}: events by layer", "event count")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_top_applications(profile: dict[str, Any], out_path: Path, top_n: int = 15) -> None:
    items = sorted(profile["applications"].items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(8, max(3, len(labels) * 0.35)))
    _bar(ax, labels, values, f"{profile['dataset']}: top applications", "active-app event count")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_session_durations(profile: dict[str, Any], out_path: Path) -> None:
    durations_min = [
        s["duration_seconds"] / 60.0 for s in profile["sessions"] if s["duration_seconds"] is not None
    ]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(durations_min, bins=15, color="#55A868")
    ax.set_title(f"{profile['dataset']}: session duration distribution")
    ax.set_xlabel("duration (minutes)")
    ax.set_ylabel("sessions")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_events_per_session(profile: dict[str, Any], out_path: Path) -> None:
    counts = [s["n_events"] for s in profile["sessions"]]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(counts, bins=15, color="#C44E52")
    ax.set_title(f"{profile['dataset']}: events per session")
    ax.set_xlabel("event count")
    ax.set_ylabel("sessions")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def generate_all(profile: dict[str, Any], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = profile["dataset"]
    paths = [
        out_dir / f"{name}_events_by_type.png",
        out_dir / f"{name}_events_by_layer.png",
        out_dir / f"{name}_top_applications.png",
        out_dir / f"{name}_session_durations.png",
        out_dir / f"{name}_events_per_session.png",
    ]
    plot_events_by_type(profile, paths[0])
    plot_events_by_layer(profile, paths[1])
    plot_top_applications(profile, paths[2])
    plot_session_durations(profile, paths[3])
    plot_events_per_session(profile, paths[4])
    return paths
