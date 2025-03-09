# AI PR Reviewer

An open-source tool to automate code reviews on GitHub PRs using any AI model. This tool analyzes pull request diffs and provides actionable feedback to improve code quality.

## Features

- **Model Agnostic**: Connect to any AI provider (OpenAI, Anthropic, Google, Mistral, Ollama, Hugging Face)
- **Focused Reviews**: Analyzes code for bugs, performance issues, security vulnerabilities, and more
- **Line-Specific Comments**: Posts comments directly on the relevant lines of code (experimental)
- **Easy Setup**: Run via GitHub Actions or locally with minimal configuration
- **Customizable**: Configure review focus areas and model settings to match your team's needs

## Quick Start

### GitHub Actions Setup

1. Add this repository to your GitHub Actions workflow:

```yaml
# .github/workflows/ai-review.yml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: yourusername/ai-pr-reviewer@main
        with:
          github-token: ${{ secrets.GH_TOKEN }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          # Optional: model: "gpt-4" 
          # Optional: focus: "security,performance"
```

2. Add your API key to your repository secrets.

### Local Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/ai-pr-reviewer.git
   cd ai-pr-reviewer
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure your settings in `config.yaml` or use environment variables.

4. Run the reviewer:
   ```bash
   export GH_TOKEN="your-github-token"
   export OPENAI_API_KEY="your-openai-key"
   export PR_REPOSITORY="owner/repo"
   export PR_NUMBER="123"
   python src/review_pr.py
   ```

## Configuration

### Supported AI Providers

- **OpenAI**: GPT-3.5, GPT-4
- **Anthropic**: Claude 3 models
- **Google**: Gemini models
- **Mistral**: Mistral models
- **Ollama**: Local model support
- **Hugging Face**: Any compatible model

### Config File

The `config.yaml` file controls the reviewer's behavior:

```yaml
model:
  provider: "openai"  # openai, anthropic, google, mistral, ollama, huggingface
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
    5. Architecture and Design
```

## Environment Variables

- `GH_TOKEN`: GitHub authentication token
- `{PROVIDER}_API_KEY`: API key for the chosen AI provider (e.g., `OPENAI_API_KEY`)
- `PR_REPOSITORY`: Repository in the format "owner/repo" (for local runs)
- `PR_NUMBER`: Pull request number (for local runs)


### Line Comment Example

```
In file src/utils.py, line 42:
Consider adding error handling here to prevent potential null reference exceptions.
```

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for more information.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Troubleshooting

### Common Issues

#### Module Import Errors
If you encounter `ModuleNotFoundError: No module named 'model_adapters'` or similar errors:
- Make sure you're running the script from the project root directory, not inside the `src` directory
- Use the module syntax when running: `python -m src.review_pr` instead of `python src/review_pr.py`

#### GitHub Authentication Errors
- Ensure your GitHub token has the necessary permissions (repo access)
- Check that you've set the `GH_TOKEN` environment variable correctly

#### API Provider Errors
- Verify that you've set the API key for your chosen provider
- Check the provider's status page for service outages
- Ensure your model has access within your API subscription/tier

## Acknowledgements

- Inspired by [CodeRabbitAI](https://coderabbit.ai/)
- Thanks to all AI model providers for their APIs

---

