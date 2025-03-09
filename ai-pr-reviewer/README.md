# AI PR Reviewer

An open-source tool to automate code reviews on GitHub PRs using any AI model. This tool analyzes pull request diffs and provides actionable feedback to improve code quality.

## Features

- **Model Agnostic**: Connect to any AI provider (OpenAI, Anthropic, Google, Mistral, Ollama, Hugging Face)
- **Focused Reviews**: Analyzes code for bugs, performance issues, security vulnerabilities, and more
- **Line-Specific Comments**: Posts comments directly on the relevant lines of code
- **Easy Setup**: Run via GitHub Actions or locally with minimal configuration
- **Customizable**: Configure review focus areas and model settings to match your team's needs

## Quick Start

### GitHub Actions Setup

1. Create a GitHub Actions workflow file in your repository:

```yaml
# .github/workflows/ai-review.yml
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

2. Add your API key to your repository secrets:
   - Go to Settings > Secrets and variables > Actions
   - Add a new secret (e.g., `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`)

For detailed setup instructions, including how to use different AI providers, see the [Setup Guide](SETUP_GUIDE.md).

### Using Anthropic Claude

To use Claude instead of OpenAI, create a custom config file in your workflow:

```yaml
- name: Create Anthropic Config
  run: |
    cd ai-pr-reviewer
    cat > config.yaml << EOF
    model:
      provider: "anthropic"
      endpoint: "https://api.anthropic.com/v1/messages"
      model: "claude-3-sonnet-20240229"
      max_tokens: 4000
    EOF

- name: Run AI PR Review
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
    GITHUB_EVENT_NUMBER: ${{ github.event.pull_request.number }}
  run: |
    cd ai-pr-reviewer
    python src/review_pr.py --verbose -c config.yaml
```

## Supported AI Providers

| Provider | Models | Environment Variable |
|----------|--------|----------------------|
| OpenAI | GPT-3.5, GPT-4 | `OPENAI_API_KEY` |
| Anthropic | Claude 3 models | `ANTHROPIC_API_KEY` |
| Google | Gemini models | `GOOGLE_API_KEY` |
| Mistral | Mistral models | `MISTRAL_API_KEY` |
| Ollama | Local models | (none needed) |
| Hugging Face | Any compatible model | `HUGGINGFACE_API_KEY` |

## Configuration Options

The tool is highly configurable through the `config.yaml` file:

```yaml
model:
  provider: "openai"  # choose your provider
  endpoint: "https://api.openai.com/v1/chat/completions"
  model: "gpt-4"
  max_tokens: 2000

review:
  line_comments: true  # enable/disable line-specific comments
  focus_areas: |
    1. Code Correctness
    2. Performance Issues
    3. Security Vulnerabilities
    4. Code Quality
```

## Troubleshooting

Common issues:

1. **API Key Not Found**: Make sure you've added the API key to your repository secrets
2. **Permission Errors**: Ensure the workflow has `pull-requests: write` permission
3. **Timeout Issues**: For large PRs, add `timeout-minutes: 10` to the job configuration

For more troubleshooting help, see the [Setup Guide](SETUP_GUIDE.md#troubleshooting).

## Advanced Usage

- **Custom Review Focus**: Specify exactly what the AI should focus on during reviews
- **Local Execution**: Run the tool on your local machine for testing
- **CI/CD Integration**: Integrate with other CI/CD tools like CircleCI or GitLab CI

See the [Setup Guide](SETUP_GUIDE.md#advanced-usage) for advanced configuration options.

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for more information.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgements

- Inspired by [CodeRabbitAI](https://coderabbit.ai/)
- Thanks to all AI model providers for their APIs

---

Made with ❤️ by the open-source community