#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "=================================================="
echo "  Deploying Animated Profile for @aryannn555"
echo "=================================================="

if [ ! -d ".git" ]; then
  echo "Initializing git repository..."
  git init
  git branch -M main
fi

if ! git remote | grep -q "origin"; then
  echo "Adding remote origin https://github.com/aryannn555/aryannn555.git..."
  git remote add origin https://github.com/aryannn555/aryannn555.git
fi

echo "Staging files..."
git add .

echo "Committing..."
git commit -m "feat: animated terminal GitHub profile README" || echo "Working tree clean, continuing..."

echo "Pushing to GitHub..."
git push -u origin main

echo ""
echo "✨ Profile deployed successfully to https://github.com/aryannn555"
