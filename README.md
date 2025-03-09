# AI PR Reviewer

[![AI PR Review](https://github.com/2dghost/VisionPRAI/actions/workflows/pr-review.yml/badge.svg)](https://github.com/2dghost/VisionPRAI/actions/workflows/pr-review.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**Use any AI model for automated code reviews on GitHub PRs!** 

AI PR Reviewer brings AI code reviews to GitHub with the freedom to choose your own AI provider. Get code reviews directly in your PRs, with line-specific comments attached to the code, using the AI model of your choice (OpenAI, Anthropic Claude, Google Gemini, etc.).


![image](https://github.com/user-attachments/assets/1c86a952-3e8d-4d7d-a188-8e50ca6e62f9)


## Features

- **🤖 Choose Your AI**: Works with OpenAI, Anthropic Claude, Google Gemini, Mistral, etc.
- **💬 In-Line Code Comments**: AI feedback appears directly alongside your code
- **🔒 Privacy Focused**: Your code never leaves your GitHub Actions environment
- **⚙️ Highly Customizable**: Configure focus areas, file filters, and model behavior
- **🚀 5-Minute Setup**: Just add the workflow file and your API key to get started

## Quick Start (5-Minute Setup)

### GitHub Actions Setup

1. **Add Workflow File**:
   Create a file at `.github/workflows/pr-review.yml` with this content:

```yaml
name: AI PR Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run AI Review
        env:
          GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # Use one of these based on your chosen AI provider:
          # OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          # GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          # MISTRAL_API_KEY: ${{ secrets.MISTRAL_API_KEY }}
          GITHUB_EVENT_NUMBER: ${{ github.event.pull_request.number }}
          PYTHONPATH: ${{ github.workspace }}
        run: |
          python src/review_pr.py --verbose
```

2. **Setup Repository Secrets**:
   - Go to your repository's **Settings** → **Secrets and variables** → **Actions**
   - Add the following secrets:
     - `GH_TOKEN`: Your GitHub token with repository access
     - `ANTHROPIC_API_KEY` (or another provider): Your AI provider's API key

3. **Copy Configuration Files**:
   - Download the [config.yaml](config.yaml) file and place it in your repository root
   - Optionally customize the settings (see Configuration section below)

That's it! Your AI PR Reviewer will run automatically on new pull requests.

### Local Setup for Development

1. **Clone this repository**:
   ```bash
   git clone https://github.com/2dghost/VisionPRAI.git
   cd VisionPRAI
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables**:
   ```bash
   # GitHub credentials
   export GH_TOKEN="your-github-personal-access-token"
   
   # Choose one provider API key:
   export ANTHROPIC_API_KEY="your-anthropic-api-key"
   # or
   export OPENAI_API_KEY="your-openai-api-key"
   
   # PR to review:
   export PR_REPOSITORY="username/repository"
   export PR_NUMBER="123"
   ```

4. **Run the reviewer**:
   ```bash
   python src/review_pr.py --verbose
   ```

## Configuration

### Supported AI Providers

- **OpenAI**: GPT-3.5, GPT-4
- **Anthropic**: Claude 3 models
- **Google**: Gemini models
- **Mistral**: Mistral models
- **Ollama**: Local model support
- **Hugging Face**: Any compatible model

### Changing AI Providers

To use a different AI model, modify the `config.yaml` file:

1. **For OpenAI (GPT-4, GPT-3.5):**
```yaml
model:
  provider: "openai"
  endpoint: "https://api.openai.com/v1/chat/completions"
  model: "gpt-4"
  max_tokens: 4000
```
Then add `OPENAI_API_KEY` to your GitHub secrets.

2. **For Anthropic (Claude):**
```yaml
model:
  provider: "anthropic"
  endpoint: "https://api.anthropic.com/v1/messages"
  model: "claude-3-haiku-20240307"  # Or another Claude model
  max_tokens: 4000
```
Then add `ANTHROPIC_API_KEY` to your GitHub secrets.

3. **For Google (Gemini):**
```yaml
model:
  provider: "google"
  endpoint: "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"
  model: "gemini-pro"
  max_tokens: 4000
```
Then add `GOOGLE_API_KEY` to your GitHub secrets.

### Full Config Example

The `config.yaml` file controls all reviewer behaviors:

```yaml
# AI Model Configuration
model:
  provider: "anthropic"  # openai, anthropic, google, mistral, ollama, huggingface
  endpoint: "https://api.anthropic.com/v1/messages"
  model: "claude-3-haiku-20240307"
  max_tokens: 4000

# Review Configuration
review:
  # Enable line-specific comments
  line_comments: true
  
  # File filtering
  file_filtering:
    enabled: true
    exclude_patterns:
      - "*.md"         # Exclude markdown files
      - "*.txt"        # Exclude text files
      - ".gitignore"   # Exclude .gitignore
      - "LICENSE"      # Exclude license files
    max_file_size: 500  # KB
  
  # Review focus areas
  focus_areas: |
    1. Code Correctness
    2. Performance Issues
    3. Security Vulnerabilities
    4. Code Quality and Maintainability
    5. Architecture and Design
```

## Customizing Your Reviews

### Focusing on Specific Areas

You can customize what the AI focuses on by modifying the `focus_areas` section in `config.yaml`:

```yaml
focus_areas: |
  1. Security Vulnerabilities
     - Input validation issues
     - Authentication and authorization flaws
     - XSS, SQL injection, CSRF vulnerabilities
     - Hardcoded credentials or secrets
  
  2. Performance Optimization
     - Database query efficiency
     - Memory usage concerns
     - Algorithmic complexity issues
```

### Excluding Files from Review

To exclude specific file types or directories:

```yaml
file_filtering:
  enabled: true
  exclude_patterns:
    - "*.md"         # Exclude all markdown
    - "tests/**"     # Exclude test files
    - "docs/**"      # Exclude documentation
    - "*.min.js"     # Exclude minified JS
```

## Examples

### Line-Specific Code Comments

The AI also adds detailed comments directly on specific lines of code:

![image](https://github.com/user-attachments/assets/6709d4f6-86a0-497f-a5ae-8534eb4f37ca)


## Environment Variables

- `GITHUB_TOKEN`: GitHub authentication token for posting comments
- `{PROVIDER}_API_KEY`: API key for your chosen AI provider:
  - `ANTHROPIC_API_KEY` for Claude models
  - `OPENAI_API_KEY` for GPT models
  - `GOOGLE_API_KEY` for Gemini models
  - etc.
- `PR_REPOSITORY`: Repository in the format "owner/repo" (for local runs)
- `PR_NUMBER`: Pull request number (for local runs)

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for more information.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

