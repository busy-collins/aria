#!/usr/bin/env python3
"""
Deploy Aria Frontend — Module 7
1. Package API Lambda
2. Terraform apply
3. Build Next.js with CloudFront URL
4. Upload to S3
5. Invalidate CloudFront cache
"""
import subprocess
import sys
import os
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def run(cmd, cwd=None, capture=False, check=True):
    print(f"  → {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    if capture:
        result = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            shell=isinstance(cmd, str)
        )
        if check and result.returncode != 0:
            print(result.stderr)
            sys.exit(1)
        return result.stdout.strip()
    else:
        result = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str))
        if check and result.returncode != 0:
            sys.exit(1)


def main():
    print("🚀 Aria Frontend Deployment")
    print("="*50)

    terraform_dir = ROOT / "terraform" / "7_frontend"
    frontend_dir  = ROOT / "frontend"
    api_dir       = ROOT / "backend" / "api"

    # ── Step 1: Package API Lambda ────────────────────────
    print("\n📦 Step 1: Packaging API Lambda...")
    run([sys.executable, "package_lambda.py"], cwd=api_dir)

    # ── Step 2: Terraform apply ───────────────────────────
    print("\n🏗️  Step 2: Deploying infrastructure...")
    run(["terraform", "init"],             cwd=terraform_dir)
    run(["terraform", "apply", "-auto-approve"], cwd=terraform_dir)

    # ── Step 3: Get outputs ───────────────────────────────
    print("\n📋 Step 3: Getting Terraform outputs...")
    outputs = json.loads(run(
        ["terraform", "output", "-json"],
        cwd=terraform_dir, capture=True
    ))

    cloudfront_url  = outputs["cloudfront_url"]["value"]
    s3_bucket       = outputs["s3_bucket_name"]["value"]
    distribution_id = outputs["cloudfront_distribution_id"]["value"]

    print(f"  CloudFront: {cloudfront_url}")
    print(f"  S3 Bucket:  {s3_bucket}")

    # ── Step 4: Build Next.js ─────────────────────────────
    print("\n🎨 Step 4: Building Next.js frontend...")

    # Write production env with real CloudFront URL
    env_file = frontend_dir / ".env.production.local"
    clerk_key = os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "")

    env_file.write_text(f"""
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY={clerk_key}
NEXT_PUBLIC_API_URL={cloudfront_url}
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
NEXT_PUBLIC_CLERK_AFTER_SIGN_IN_URL=/dashboard
NEXT_PUBLIC_CLERK_AFTER_SIGN_OUT_URL=/
""".strip())

    if not (frontend_dir / "node_modules").exists():
        run(["npm", "install"], cwd=frontend_dir)

    run(["npm", "run", "build"], cwd=frontend_dir)

    out_dir = frontend_dir / "out"
    if not out_dir.exists():
        print("❌ Build failed — no out/ directory")
        sys.exit(1)

    # ── Step 5: Upload to S3 ──────────────────────────────
    print(f"\n📤 Step 5: Uploading to S3...")

    run([
        "aws", "s3", "sync",
        str(out_dir) + "/",
        f"s3://{s3_bucket}/",
        "--delete",
        "--cache-control", "max-age=31536000,public"
    ])

    # HTML files should not be cached
    run([
        "aws", "s3", "cp",
        str(out_dir) + "/",
        f"s3://{s3_bucket}/",
        "--recursive",
        "--exclude", "*",
        "--include", "*.html",
        "--cache-control", "no-cache,no-store,must-revalidate"
    ])

    # ── Step 6: Invalidate CloudFront ─────────────────────
    print(f"\n🔄 Step 6: Invalidating CloudFront cache...")
    run([
        "aws", "cloudfront", "create-invalidation",
        "--distribution-id", distribution_id,
        "--paths", "/*"
    ])

    print("\n" + "="*50)
    print("✅ Deployment complete!")
    print(f"\n🌐 Your app: {cloudfront_url}")
    print(f"📊 Dashboard: {cloudfront_url}/dashboard")


if __name__ == "__main__":
    main()