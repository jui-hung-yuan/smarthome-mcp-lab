"""Build Lambda deployment package for AgentCore Gateway handler.

Creates dist/smarthome-lambda.zip containing only the modules needed:
  - smarthome/cloud/iot_commands.py
  - smarthome/lambda_handler.py
  - smarthome/logging/dynamo_logger.py

boto3 is already available in the Lambda runtime, so no dependencies are bundled.

Usage:
    uv run python scripts/package_lambda.py
"""

import os
import zipfile
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
ZIP_NAME = "smarthome-lambda.zip"

# Files to include (relative to src/)
INCLUDE_FILES = [
    "smarthome/__init__.py",
    "smarthome/cloud/__init__.py",
    "smarthome/cloud/iot_commands.py",
    "smarthome/lambda_handler.py",
    "smarthome/logging/__init__.py",
    "smarthome/logging/dynamo_logger.py",
]


def build_package() -> Path:
    """Build the Lambda deployment zip.

    Returns:
        Path to the created zip file
    """
    DIST_DIR.mkdir(exist_ok=True)
    zip_path = DIST_DIR / ZIP_NAME

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in INCLUDE_FILES:
            src_path = SRC_DIR / rel_path
            if not src_path.exists():
                raise FileNotFoundError(f"Required file not found: {src_path}")
            zf.write(src_path, rel_path)
            print(f"  Added: {rel_path}")

    size_kb = os.path.getsize(zip_path) / 1024
    print(f"\nPackage created: {zip_path} ({size_kb:.1f} KB)")
    print(f"Files included: {len(INCLUDE_FILES)}")

    return zip_path


def verify_package(zip_path: Path) -> None:
    """Verify the package contents."""
    print("\nPackage contents:")
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            print(f"  {info.filename} ({info.file_size} bytes)")

    # Verify excluded modules are not present
    excluded = ["tapo", "fastmcp", "awsiotsdk", "devices", "mcp_servers", "bridge"]
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        for module in excluded:
            matches = [n for n in names if module in n]
            if matches:
                print(f"\nWARNING: Excluded module '{module}' found in package: {matches}")


if __name__ == "__main__":
    print("Building Lambda deployment package...")
    print()
    zip_path = build_package()
    verify_package(zip_path)
    print("\nDone. Upload to Lambda with:")
    print(f"  uv run python scripts/create_lambda.py")
