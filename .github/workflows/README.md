# GitHub Actions Workflows

## PR Review Workflow

The `pr-review.yml` workflow automatically analyzes pull requests using AI to provide code review comments and suggestions.

### Workflow Details

- **Trigger**: Runs automatically when a PR is opened, synchronized, or reopened
- **Required Secrets**:
  - `GH_TOKEN`: GitHub token with permission to read repositories and write PR comments
  - At least one model API key based on your provider choice (see below)

### Available AI Providers

Configure your chosen AI provider in `config.yaml`:

- OpenAI: Set `OPENAI_API_KEY` secret
- Anthropic: Set `ANTHROPIC_API_KEY` secret
- Google: Set `GOOGLE_API_KEY` secret
- Mistral: Set `MISTRAL_API_KEY` secret
- Hugging Face: Set `HUGGINGFACE_API_KEY` secret
- Ollama: No API key needed for local deployments

### Customization

Modify the `config.yaml` file to:
- Change the AI provider
- Adjust model parameters
- Customize review focus areas
- Enable/disable line-specific comments

### Manual Testing

To test this workflow locally:

```bash
# Set required environment variables
export GH_TOKEN="your-github-token"
export PR_REPOSITORY="owner/repo"
export PR_NUMBER="123"
export OPENAI_API_KEY="your-openai-key"  # Or other provider key

# Run the review
python -m src.review_pr --verbose
```