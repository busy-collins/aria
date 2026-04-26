#!/usr/bin/env python3
"""
Deploy the Aria Researcher service.
This script:
1. Builds a Docker image for linux/amd64
2. Pushes it to ECR
3. Triggers App Runner deployment
4. Waits for deployment to complete
"""

import subprocess
import sys
import json
import time
from pathlib import Path


def run_command(cmd, cwd=None, check=True, capture_output=False):
    """Run a command and optionally capture output."""
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")

    if capture_output:
        result = subprocess.run(
            cmd, cwd=cwd,
            capture_output=True, text=True,
            shell=isinstance(cmd, str)
        )
        if check and result.returncode != 0:
            print(f"Error: {result.stderr}")
            sys.exit(1)
        return result.stdout.strip()
    else:
        result = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str))
        if check and result.returncode != 0:
            sys.exit(1)
        return None


def check_prerequisites():
    """Check that all required tools are installed."""
    print("🔍 Checking prerequisites...")

    tools = {
        "docker":    "Docker is required for building images",
        "aws":       "AWS CLI is required for ECR and App Runner",
        "terraform": "Terraform is required to get ECR URL",
    }

    for tool, message in tools.items():
        try:
            run_command([tool, "--version"], capture_output=True)
            print(f"  ✅ {tool} is installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"  ❌ {message}")
            sys.exit(1)

    # Check Docker is running
    try:
        run_command(["docker", "info"], capture_output=True)
        print("  ✅ Docker is running")
    except subprocess.CalledProcessError:
        print("  ❌ Docker is not running. Please start Docker Desktop.")
        sys.exit(1)

    # Check AWS credentials
    try:
        run_command(["aws", "sts", "get-caller-identity"], capture_output=True)
        print("  ✅ AWS credentials configured")
    except subprocess.CalledProcessError:
        print("  ❌ AWS credentials not configured. Run 'aws configure'")
        sys.exit(1)


def get_ecr_url():
    """Get ECR repository URL from Terraform outputs."""
    print("\n📋 Getting ECR URL from Terraform...")

    terraform_dir = Path(__file__).parent.parent.parent / "terraform" / "4_researcher"

    if not terraform_dir.exists():
        print(f"  ❌ Terraform directory not found: {terraform_dir}")
        sys.exit(1)

    ecr_url = run_command(
        ["terraform", "output", "-raw", "ecr_repository_url"],
        cwd    = terraform_dir,
        capture_output = True
    )

    if not ecr_url:
        print("  ❌ Could not get ECR URL. Have you run terraform apply?")
        sys.exit(1)

    print(f"  ✅ ECR URL: {ecr_url}")
    return ecr_url


def get_app_runner_arn():
    """Get App Runner service ARN from Terraform outputs."""
    terraform_dir = Path(__file__).parent.parent.parent / "terraform" / "4_researcher"

    arn = run_command(
        ["terraform", "output", "-raw", "app_runner_service_arn"],
        cwd            = terraform_dir,
        capture_output = True,
        check          = False
    )

    return arn if arn else None


def login_to_ecr(ecr_url: str):
    """Authenticate Docker with ECR."""
    print("\n🔐 Logging in to ECR...")

    # Extract region from ECR URL
    # Format: 975022060655.dkr.ecr.us-east-1.amazonaws.com/...
    region = ecr_url.split(".")[3]
    registry = ecr_url.split("/")[0]

    password = run_command(
        ["aws", "ecr", "get-login-password", "--region", region],
        capture_output = True
    )

    # Pipe password to docker login
    result = subprocess.run(
        ["docker", "login",
         "--username", "AWS",
         "--password-stdin",
         registry],
        input  = password,
        text   = True,
        capture_output = True
    )

    if result.returncode != 0:
        print(f"  ❌ ECR login failed: {result.stderr}")
        sys.exit(1)

    print("  ✅ Logged in to ECR successfully")


def build_and_push(ecr_url: str):
    """Build Docker image and push to ECR."""
    # Build context is backend/ so Docker can access shared/
    backend_dir = Path(__file__).parent.parent

    print(f"\n🐳 Building Docker image for linux/amd64...")

    run_command([
        "docker", "buildx", "build",
        "--platform", "linux/amd64",
        "--no-cache",
        "-f", "researcher/Dockerfile",    # Dockerfile location
        "-t", f"{ecr_url}:latest",
        "--push",
        "."                               # build context = backend/
    ], cwd=backend_dir)

    print(f"  ✅ Docker image pushed successfully!")

    # Get and display the image digest
    digest = run_command([
        "docker", "inspect",
        "--format={{index .RepoDigests 0}}",
        f"{ecr_url}:latest"
    ], capture_output=True, check=False)

    if digest:
        print(f"  📌 Image digest: {digest}")

    return digest


def deploy_to_app_runner(service_arn: str):
    """Trigger App Runner deployment."""
    print(f"\n🚀 Triggering App Runner deployment...")

    if not service_arn:
        print("  ⚠️  No App Runner service ARN found")
        print("  Run: cd terraform/4_researcher && terraform apply")
        return None

    result = run_command([
        "aws", "apprunner", "start-deployment",
        "--service-arn", service_arn,
        "--region", "us-east-1",
        "--output", "json"
    ], capture_output=True, check=False)

    if result:
        data = json.loads(result)
        operation_id = data.get("OperationId", "unknown")
        print(f"  ✅ Deployment started — Operation ID: {operation_id}")
        return operation_id

    return None


def wait_for_deployment(service_arn: str, timeout_minutes: int = 10):
    """Wait for App Runner deployment to complete."""
    if not service_arn:
        return

    print(f"\n⏳ Waiting for deployment to complete (max {timeout_minutes} min)...")

    timeout   = timeout_minutes * 60
    interval  = 15
    elapsed   = 0

    while elapsed < timeout:
        status = run_command([
            "aws", "apprunner", "describe-service",
            "--service-arn", service_arn,
            "--region", "us-east-1",
            "--query", "Service.Status",
            "--output", "text"
        ], capture_output=True, check=False)

        print(f"  Status: {status} ({elapsed}s elapsed)")

        if status == "RUNNING":
            print("  ✅ Deployment successful — service is RUNNING")
            return True
        elif status in ("CREATE_FAILED", "DELETE_FAILED", "OPERATION_IN_PROGRESS"):
            if elapsed > 30 and status == "OPERATION_IN_PROGRESS":
                # Still deploying — keep waiting
                pass
            elif status in ("CREATE_FAILED", "DELETE_FAILED"):
                print(f"  ❌ Deployment failed with status: {status}")
                print("  Check App Runner logs in AWS Console")
                return False

        time.sleep(interval)
        elapsed += interval

    print(f"  ⚠️  Timeout after {timeout_minutes} minutes")
    print("  Check App Runner console for status")
    return False


def verify_health(service_url: str):
    """Verify the service health endpoint."""
    print(f"\n🏥 Verifying service health...")

    import urllib.request
    import urllib.error

    url = f"https://{service_url}/health"

    # Retry a few times — service may need a moment to warm up
    for attempt in range(5):
        try:
            response = urllib.request.urlopen(url, timeout=10)
            data     = json.loads(response.read())
            print(f"  ✅ Service is healthy!")
            print(f"  Response: {json.dumps(data, indent=2)}")
            return True
        except Exception as e:
            print(f"  Attempt {attempt + 1}/5: {e}")
            time.sleep(10)

    print("  ⚠️  Health check failed — service may still be warming up")
    return False


def get_service_url():
    """Get App Runner service URL from Terraform outputs."""
    terraform_dir = Path(__file__).parent.parent.parent / "terraform" / "4_researcher"

    url = run_command(
        ["terraform", "output", "-raw", "app_runner_service_url"],
        cwd            = terraform_dir,
        capture_output = True,
        check          = False
    )

    return url if url else None


def main():
    """Main deployment function."""
    print("🚀 Aria Researcher — Deployment Script")
    print("=" * 50)

    # Step 1: Check prerequisites
    check_prerequisites()

    # Step 2: Get ECR URL from Terraform
    ecr_url = get_ecr_url()

    # Step 3: Get App Runner ARN
    service_arn = get_app_runner_arn()

    # Step 4: Login to ECR
    login_to_ecr(ecr_url)

    # Step 5: Build and push Docker image
    build_and_push(ecr_url)

    # Step 6: Deploy to App Runner (if service exists)
    if service_arn:
        deploy_to_app_runner(service_arn)

        # Step 7: Wait for deployment
        success = wait_for_deployment(service_arn)

        # Step 8: Verify health
        if success:
            service_url = get_service_url()
            if service_url:
                verify_health(service_url)
                print("\n" + "=" * 50)
                print("✅ Deployment complete!")
                print(f"\n🌐 Researcher service URL:")
                print(f"   https://{service_url}")
                print(f"\n📊 Test the researcher:")
                print(f"   curl https://{service_url}/health")
                print(f"   uv run test_research.py")
    else:
        # No App Runner service yet — Terraform needs to create it
        print("\n⚠️  App Runner service not found in Terraform state")
        print("   Image is now in ECR — run Terraform to create the service:")
        print("\n   cd terraform/4_researcher")
        print("   terraform apply")
        print("\n" + "=" * 50)
        print("✅ Image pushed successfully!")
        print(f"   ECR: {ecr_url}:latest")


if __name__ == "__main__":
    main()