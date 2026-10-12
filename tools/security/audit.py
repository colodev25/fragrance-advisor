"""Audit exact Python locks; retain raw findings and narrowly scoped exceptions."""
import argparse
from datetime import date
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LOCKS = ("requirements.txt", "requirements/dev.txt", "requirements/catalog.txt", "requirements/security.txt")


def evaluate(report, policy, today=None):
    today = today or date.today()
    if policy.get("version") != 1 or not isinstance(policy.get("exceptions"), list):
        raise ValueError("Invalid exception policy")
    exceptions = policy["exceptions"]
    for entry in exceptions:
        if (not isinstance(entry.get("ids"), list) or not entry["ids"] or
                not entry.get("reason") or not entry.get("source") or
                not entry.get("package") or not entry.get("version")):
            raise ValueError("Incomplete security exception")
        if date.fromisoformat(entry["expires"]) <= today:
            raise ValueError("Expired security exception: " + entry["ids"][0])
    dependencies = report["dependencies"]
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("Invalid audit report")
    failures, accepted = [], []
    for dependency in dependencies:
        if dependency.get("skip_reason"):
            failures.append({"package": dependency["name"], "error": "package not audited"})
        for vulnerability in dependency.get("vulns", []):
            identifiers = {vulnerability["id"], *vulnerability.get("aliases", [])}
            match = next((entry for entry in exceptions if entry["package"] == dependency["name"]
                          and entry["version"] == dependency["version"]
                          and identifiers.intersection(entry["ids"])), None)
            finding = {"package": dependency["name"], "version": dependency["version"],
                       "id": vulnerability["id"], "aliases": sorted(identifiers),
                       "fix_versions": vulnerability.get("fix_versions", [])}
            # A newly available correction invalidates the temporary mitigation.
            if match and not finding["fix_versions"]:
                accepted.append({**finding, "expires": match["expires"], "reason": match["reason"]})
            else:
                failures.append(finding)
    return {"unaccepted": failures, "mitigated": accepted}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    policy = json.loads((ROOT / "tools/security/exceptions.json").read_text(encoding="utf-8"))
    results = {}
    failed = False
    for lock in LOCKS:
        target = args.output / (Path(lock).name + ".audit.json")
        result = subprocess.run([sys.executable, "-m", "pip_audit", "--no-deps", "--disable-pip",
                                 "-r", str(ROOT / lock), "-f", "json", "-o", str(target)],
                                timeout=180, check=False)
        if result.returncode not in (0, 1) or not target.is_file():
            raise RuntimeError("Audit failed or unavailable: " + lock)
        evaluated = evaluate(json.loads(target.read_text(encoding="utf-8")), policy)
        results[lock] = evaluated
        failed |= bool(evaluated["unaccepted"])
        print(f"{lock}: {len(evaluated['unaccepted'])} unaccepted, {len(evaluated['mitigated'])} mitigated findings")
    (args.output / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
