#!/usr/bin/env python3
"""
Package the agents Lambda with all dependencies.
Builds for linux/amd64 using Docker to ensure correct architecture.
"""
import subprocess
import shutil
import os
from pathlib import Path

AGENTS_DIR  = Path(__file__).parent
BUILD_DIR   = AGENTS_DIR / "build"
OUTPUT_ZIP  = Path(__file__).parent.parent.parent / "terraform" / "6_agents" / "agents_lambda.zip"


def build_with_docker():
    """Use Docker to install dependencies for linux/amd64."""
    print("  Using Docker to build for linux/amd64...")

    # Clean build directory
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir()

    subprocess.run([
        "docker", "run",
        "--platform", "linux/amd64",
        "--rm",
        "-v", f"{BUILD_DIR}:/build",
        "python:3.12-slim",
        "pip", "install",
        "openai-agents",
        "openai",
        "httpx",
        "boto3",
        "pydantic",
        "langsmith",
        "python-dotenv",
        "--target", "/build",
        "--quiet"
    ], check=True)

    print("  ✅ Dependencies installed for linux/amd64")


def copy_source_files():
    """Copy handler and shared files into build directory."""
    print("  Copying handler files...")

    handler_files = [
        "analyst_handler.py",
        "writer_handler.py",
        "critic_handler.py",
        "analyst.py",
        "writer.py",
        "critic.py",
        "researcher.py",
    ]

    for filename in handler_files:
        src = AGENTS_DIR / filename
        if src.exists():
            shutil.copy2(src, BUILD_DIR / filename)
            print(f"    ✅ {filename}")
        else:
            print(f"    ⚠️  {filename} not found — skipping")

    # Copy shared package
    print("  Copying shared package...")
    shared_src = AGENTS_DIR.parent / "shared"
    shared_dst = BUILD_DIR / "shared"

    if shared_src.exists():
        shutil.copytree(shared_src, shared_dst)
        print(f"    ✅ shared/")
    else:
        print(f"    ❌ shared/ not found!")
        raise FileNotFoundError("shared/ package missing")


def create_zip():
    """Zip the build directory."""
    print(f"  Creating zip...")

    OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing zip
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    shutil.make_archive(
        str(OUTPUT_ZIP.with_suffix("")),
        "zip",
        str(BUILD_DIR)
    )

    size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print(f"  ✅ Package created: {size_mb:.1f} MB")
    print(f"  📍 Location: {OUTPUT_ZIP}")


def main():
    print("📦 Packaging agents Lambda for linux/amd64...")
    print("="*50)

    # Check Docker is running
    try:
        subprocess.run(
            ["docker", "info"],
            capture_output=True, check=True
        )
    except subprocess.CalledProcessError:
        print("❌ Docker is not running — please start Docker Desktop")
        raise

    build_with_docker()
    copy_source_files()
    create_zip()

    print("="*50)
    print("✅ Lambda package ready!")
    print("\nNext step:")
    print("  cd terraform/6_agents && terraform apply")


if __name__ == "__main__":
    main()