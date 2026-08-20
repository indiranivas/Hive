"""Build the sideloadable Teams app package.

    python scripts/build_teams_package.py                 # reads BOT_APP_ID from env/.env
    python scripts/build_teams_package.py --app-id <guid>
    python scripts/build_teams_package.py --out build/hive.zip

Writes dist/hive-teams-app.zip -- upload via Teams > Apps > Manage your apps >
Upload an app > Upload a custom app.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PACKAGE = REPO_ROOT / "appPackage"
DIST = REPO_ROOT / "dist"
PLACEHOLDER = "${{BOT_APP_ID}}"
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def app_id_from_env() -> str | None:
    if os.environ.get("BOT_APP_ID"):
        return os.environ["BOT_APP_ID"]
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "BOT_APP_ID" and value.strip():
                return value.strip().strip('"').strip("'")
    return None


def build(app_id: str, target: Path | None = None) -> Path:
    manifest_text = (APP_PACKAGE / "manifest.json").read_text(encoding="utf-8")
    manifest_text = manifest_text.replace(PLACEHOLDER, app_id)
    manifest = json.loads(manifest_text)  # fail loudly on malformed JSON

    target = target or (DIST / "hive-teams-app.zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        for icon in ("color.png", "outline.png"):
            bundle.write(APP_PACKAGE / icon, icon)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the Hive Teams app")
    parser.add_argument("--app-id", help="Azure Bot / Entra app registration GUID")
    parser.add_argument(
        "--out", type=Path, help="output zip path (default: dist/hive-teams-app.zip)"
    )
    args = parser.parse_args()

    app_id = args.app_id or app_id_from_env()
    if not app_id:
        print(
            "No bot app id. Register an Azure Bot, then either set BOT_APP_ID in .env "
            "or pass --app-id <guid>.",
            file=sys.stderr,
        )
        return 2
    if not GUID_RE.match(app_id):
        print(f"'{app_id}' is not a GUID -- Teams will reject the package.", file=sys.stderr)
        return 2

    target = build(app_id, args.out)
    try:
        shown = target.relative_to(REPO_ROOT)
    except ValueError:
        shown = target
    print(f"wrote {shown} (botId {app_id})")
    print("Upload: Teams > Apps > Manage your apps > Upload an app > Upload a custom app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
