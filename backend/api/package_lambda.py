#!/usr/bin/env python3
"""Package the API Lambda with dependencies for linux/amd64."""
import subprocess
import shutil
from pathlib import Path

API_DIR    = Path(__file__).parent
BUILD_DIR  = API_DIR / "build"
OUTPUT_ZIP = Path(__file__).parent.parent.parent / "terraform" / "7_frontend" / "api_lambda.zip"


def main():
    print("📦 Packaging API Lambda for linux/amd64...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir()

    # Install dependencies for linux/amd64 via Docker
    subprocess.run([
        "docker", "run",
        "--platform", "linux/amd64",
        "--rm",
        "-v", f"{BUILD_DIR}:/build",
        "python:3.12-slim",
        "pip", "install",
        "fastapi",
        "mangum",
        "boto3",
        "pydantic",
        "python-dotenv",
        "fastapi-clerk-auth",
        "httpx",
        "--target", "/build",
        "--quiet"
    ], check=True)

    print("  ✅ Dependencies installed")

    # Copy API files
    for filename in ["main.py"]:
        src = API_DIR / filename
        if src.exists():
            shutil.copy2(src, BUILD_DIR / filename)
            print(f"  ✅ {filename}")

    # Create zip
    OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    shutil.make_archive(
        str(OUTPUT_ZIP.with_suffix("")),
        "zip",
        str(BUILD_DIR)
    )

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"  ✅ Package created: {size_mb:.1f} MB")
    print(f"  📍 {OUTPUT_ZIP}")
    print("\nNext: cd terraform/7_frontend && terraform apply")


if __name__ == "__main__":
    main()