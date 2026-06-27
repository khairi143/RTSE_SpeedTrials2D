import csv
import os

CSV_PATH = "scores.csv"


def parse_score(text):
    return float(text)


def format_table(rows):
    if not rows:
        return "(no runs recorded yet)"
    lines = [f"{'Run':>5} | {'Score':>10}", "-" * 18]
    for run, score in rows:
        lines.append(f"{run:>5} | {score:>10}")
    return "\n".join(lines)


def next_run_number(rows):
    if not rows:
        return 1
    return max(run for run, _ in rows) + 1


def load_scores(path=CSV_PATH):
    if not os.path.exists(path):
        return []
    rows = []
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append((int(row["run"]), float(row["score"])))
    except (csv.Error, KeyError, ValueError, TypeError):
        return []
    return rows


def save_scores(rows, path=CSV_PATH):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "score"])
        for run, score in rows:
            writer.writerow([run, score])
