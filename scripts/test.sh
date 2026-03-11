#!/bin/bash
set -e

# Get the project root directory (parent of scripts/)
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Check if image exists, build only if needed or if --rebuild flag is passed
if [ "$1" = "--rebuild" ]; then
    shift  # Remove --rebuild from arguments
    echo "Rebuilding test image..."
    docker build -f "$PROJECT_ROOT/Dockerfile.test" -t llmflows-test "$PROJECT_ROOT"
elif ! docker image inspect llmflows-test >/dev/null 2>&1; then
    echo "Building test image (first time)..."
    docker build -f "$PROJECT_ROOT/Dockerfile.test" -t llmflows-test "$PROJECT_ROOT"
else
    echo "Using existing test image (use --rebuild to update dependencies)"
fi

# Run tests with project mounted
echo "Running tests..."
docker run --rm \
  -v "$PROJECT_ROOT:/app" \
  -w /app \
  llmflows-test \
  pytest --cov=llmflows --cov-report=term-missing -v "$@"

echo ""
echo "✅ Tests complete!"

