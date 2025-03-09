# AI PR Reviewer Setup Guide

This guide provides detailed instructions for setting up and configuring the AI PR Reviewer tool for your repositories.

## Table of Contents

1. [Basic Setup](#basic-setup)
2. [Configuration Options](#configuration-options)
3. [AI Provider Configuration](#ai-provider-configuration)
4. [GitHub Actions Setup](#github-actions-setup)
5. [Troubleshooting](#troubleshooting)
6. [Advanced Usage](#advanced-usage)

## Basic Setup

The easiest way to use AI PR Reviewer is through GitHub Actions. Here's a basic setup:

### Step 1: Create the GitHub Actions Workflow File

Create a file at `.github/workflows/ai-review.yml` in your repository:

```yaml
name: AI PR Reviewer

on:
  pull_request:
    types: [opened, synchronize, reopened]
    
jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v3
        with:
          fetch-depth: 0
      
      - name: Checkout AI PR Reviewer
        uses: actions/checkout@v3
        with:
          repository: 2dghost/VisionPRAI
          path: ai-pr-reviewer
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
          cache: 'pip'
      
      - name: Install Dependencies
        run: |
          cd ai-pr-reviewer
          pip install -r requirements.txt
      
      - name: Run AI PR Review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # Choose ONE of these API keys based on your preferred provider:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          # ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          # MISTRAL_API_KEY: ${{ secrets.MISTRAL_API_KEY }}
          GITHUB_EVENT_NUMBER: ${{ github.event.pull_request.number }}
        run: |
          cd ai-pr-reviewer
          python src/review_pr.py --verbose
```

### Step 2: Add API Key to Repository Secrets

1. Go to your repository on GitHub
2. Click on "Settings" > "Secrets and variables" > "Actions"
3. Click "New repository secret"
4. Add your API key with the appropriate name:
   - `OPENAI_API_KEY` for OpenAI
   - `ANTHROPIC_API_KEY` for Anthropic (Claude)
   - `GOOGLE_API_KEY` for Google (Gemini)
   - `MISTRAL_API_KEY` for Mistral
5. Click "Add secret"

That's it! The AI PR Reviewer will now automatically run on all new pull requests.

## Configuration Options

The AI PR Reviewer is highly configurable. You can customize:

- Which AI provider to use
- What model to use
- What areas to focus on in the review
- Whether to include line-specific comments

### Using a Custom Configuration File

To use a custom configuration:

1. Create a config file in your workflow:

```yaml
- name: Create Custom Config
  run: |
    cd ai-pr-reviewer
    cat > custom_config.yaml << EOF
    # AI PR Reviewer Configuration
    model:
      provider: "openai"  # Change to your preferred provider
      endpoint: "https://api.openai.com/v1/chat/completions"
      model: "gpt-4"
      max_tokens: 2000
    
    review:
      line_comments: true
      focus_areas: |
        1. Code Correctness
        2. Performance Issues
        3. Security Vulnerabilities
        4. Code Quality and Maintainability
    EOF
```

2. Use this config in the review step:

```yaml
- name: Run AI PR Review
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    GITHUB_EVENT_NUMBER: ${{ github.event.pull_request.number }}
  run: |
    cd ai-pr-reviewer
    python src/review_pr.py --verbose -c custom_config.yaml
```

## AI Provider Configuration

### OpenAI (GPT-4, GPT-3.5)

```yaml
model:
  provider: "openai"
  endpoint: "https://api.openai.com/v1/chat/completions"
  model: "gpt-4"  # or "gpt-3.5-turbo" for a less expensive option
  max_tokens: 2000
```

Environment variable: `OPENAI_API_KEY`

### Anthropic (Claude)

```yaml
model:
  provider: "anthropic"
  endpoint: "https://api.anthropic.com/v1/messages"
  model: "claude-3-opus-20240229"  # or "claude-3-sonnet-20240229" or "claude-3-haiku-20240307"
  max_tokens: 4000
```

Environment variable: `ANTHROPIC_API_KEY`

### Google (Gemini)

```yaml
model:
  provider: "google"
  endpoint: "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
  model: "gemini-pro"
  max_tokens: 2048
```

Environment variable: `GOOGLE_API_KEY`

### Mistral

```yaml
model:
  provider: "mistral"
  endpoint: "https://api.mistral.ai/v1/chat/completions"
  model: "mistral-large-latest"  # or "mistral-medium" or "mistral-small"
  max_tokens: 2048
```

Environment variable: `MISTRAL_API_KEY`

### Ollama (Local Models)

```yaml
model:
  provider: "ollama"
  endpoint: "http://localhost:11434/api/generate"
  model: "llama3"  # or any model you have installed in Ollama
  max_tokens: 2048
```

No API key needed (local server).

## GitHub Actions Setup

### Required Permissions

The GitHub Actions workflow needs permission to read repository contents and write to pull requests. Add this to your workflow:

```yaml
permissions:
  contents: read
  pull-requests: write
```

### Workflow Triggers

By default, the workflow runs on:
- New pull requests
- Updates to existing pull requests
- Reopened pull requests

You can customize this in the `on` section of the workflow file.

### Workflow Secrets

The workflow requires:
1. `GITHUB_TOKEN` - automatically provided by GitHub Actions
2. Your API key for the AI provider you're using

### Using with Private Repositories

For private repositories, make sure the workflow has access to checkout private code:

```yaml
- name: Checkout Repository
  uses: actions/checkout@v3
  with:
    fetch-depth: 0
    token: ${{ secrets.GITHUB_TOKEN }}
```

## Troubleshooting

### Common Issues

1. **API Key Not Found**
   - Error: `API key for [provider] not found in config or environment variables`
   - Solution: Add the API key to your repository secrets with the correct name

2. **Rate Limiting**
   - Error: Mentions rate limits or too many requests
   - Solution: Add retry logic or reduce the frequency of reviews

3. **Timeout Issues**
   - Error: Workflow times out during execution
   - Solution: Add `timeout-minutes: 10` to the job configuration

4. **Permission Errors**
   - Error: Unable to post comments to PR
   - Solution: Make sure the workflow has `pull-requests: write` permission

### Debugging

Add the `--verbose` flag to the `review_pr.py` command to get more detailed logs:

```yaml
python src/review_pr.py --verbose -c config.yaml
```

## Advanced Usage

### Custom Review Focus

You can customize what the AI focuses on during reviews by editing the `focus_areas` section:

```yaml
review:
  focus_areas: |
    1. Security Vulnerabilities
       - SQL injection
       - XSS vulnerabilities
       - Authentication issues
    
    2. Performance Optimization
       - Big O complexity
       - Memory usage
       - Database query efficiency
```

### Line-Specific Comments

Enable or disable line-specific comments with:

```yaml
review:
  line_comments: true  # or false
```

### Running Locally

To run the tool locally:

```bash
# Clone the repository
git clone https://github.com/2dghost/VisionPRAI.git
cd VisionPRAI

# Install dependencies
pip install -r requirements.txt

# Configure your API key
export OPENAI_API_KEY="your-api-key"

# Run the review
python src/review_pr.py -c config.yaml --verbose
```

### Integrating with CI/CD Pipelines

You can integrate the AI PR Reviewer with other CI/CD tools by:

1. Installing the tool on your CI server
2. Setting up the required environment variables
3. Running the review script as part of your pipeline

For example, with CircleCI:

```yaml
version: 2.1
jobs:
  review:
    docker:
      - image: cimg/python:3.10
    steps:
      - checkout
      - run:
          name: Clone AI PR Reviewer
          command: git clone https://github.com/2dghost/VisionPRAI.git ai-pr-reviewer
      - run:
          name: Install Dependencies
          command: pip install -r ai-pr-reviewer/requirements.txt
      - run:
          name: Run AI Review
          command: |
            cd ai-pr-reviewer
            python src/review_pr.py --verbose
          environment:
            GITHUB_TOKEN: ${GITHUB_TOKEN}
            OPENAI_API_KEY: ${OPENAI_API_KEY}
```