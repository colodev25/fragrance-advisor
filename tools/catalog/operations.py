"""Report CLI and read-only GitHub artifact freshness monitor."""
import argparse
from datetime import date, datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.catalog_operations import quality, write_report


def alternating_day(day):
    # Fixed local-date anchor: never resets at month boundaries.
    return (day - date(2026, 10, 13)).days % 2 == 0


def freshness(report, now=None, max_hours=72):
    now = now or datetime.now(timezone.utc)
    if report.get("version") != 1 or report.get("status") != "success" or not re.fullmatch(r"[a-f0-9]{64}", report.get("catalog_hash", "")):
        raise ValueError("No verified synchronization report available")
    timestamp = datetime.fromisoformat(report["verified_at"])
    if timestamp.utcoffset() is None:
        raise ValueError("Synchronization timestamp must include timezone")
    age = (now - timestamp).total_seconds() / 3600
    if age < -5 / 60:
        raise ValueError("Synchronization timestamp is in the future")
    return {"verified_at": timestamp.isoformat(), "age_hours": round(max(0, age), 2),
            "max_hours": max_hours, "stale": age > max_hours}


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("Artifact redirect must use HTTPS")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            redirected.remove_header("Authorization")
        return redirected


def latest_report(repo, token):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    opener = build_opener(SafeRedirect())
    def get(path, binary=False):
        req = Request("https://api.github.com/repos/" + repo + path,
                      headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
        with opener.open(req, timeout=30) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
        if len(payload) > 2 * 1024 * 1024:
            raise ValueError("Artifact or metadata too large")
        return payload if binary else json.loads(payload)
    runs = get("/actions/workflows/catalog-sync.yml/runs?status=success&per_page=10")["workflow_runs"]
    for run in runs:
        artifacts = get(f"/actions/runs/{int(run['id'])}/artifacts")["artifacts"]
        item = next((a for a in artifacts if a["name"] == "catalog-sync-report" and not a["expired"]), None)
        if item:
            payload = get(f"/actions/artifacts/{int(item['id'])}/zip", binary=True)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                member = next((i for i in archive.infolist() if i.filename == "catalog_sync_report.json"), None)
                if member is None or member.file_size > 2 * 1024 * 1024:
                    raise ValueError("Invalid report artifact")
                return json.loads(archive.read(member))
    raise ValueError("No successful catalog report found; run synchronization first")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["schedule", "enrichment", "monitor"])
    parser.add_argument("--directory", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "schedule":
        from zoneinfo import ZoneInfo
        run = os.getenv("GITHUB_EVENT_NAME") != "schedule" or alternating_day(datetime.now(ZoneInfo("Europe/Rome")).date())
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("run=" + str(run).lower() + "\n")
    elif args.mode == "enrichment":
        products = json.loads((args.directory / "catalog.json").read_text(encoding="utf-8"))
        state = json.loads((args.directory / "catalog_enrichment_state.json").read_text(encoding="utf-8"))
        from collections import Counter
        report = {"reported_at": datetime.now(timezone.utc).isoformat(), "quality": quality(products),
                  "queue": dict(Counter(e["status"] for e in state["queue"].values())),
                  "reserved_tokens": sum(r["tokens"] for r in state["reservations"])}
        write_report(args.output or args.directory / "catalog_enrichment_report.json", report)
    else:
        report = latest_report(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        result = freshness(report)
        print(json.dumps(result))
        if args.output:
            write_report(args.output, result)
        if result["stale"]:
            raise SystemExit("Catalog verification is older than 72 hours; inspect sync workflow")


if __name__ == "__main__":
    main()
