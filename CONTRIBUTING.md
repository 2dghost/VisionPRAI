# Contributing to AI PR Reviewer

Thank you for your interest in contributing to the AI PR Reviewer project! We welcome contributions from everyone, whether it's reporting a bug, suggesting a feature, or submitting code changes.

## Code of Conduct

By participating in this project, you agree to act with respect, kindness, and empathy toward other contributors. We aim to foster an inclusive and welcoming community.

## Development Guidelines

This project uses Cursor AI for development assistance. Please follow these guidelines:

1. Install [Cursor](https://cursor.sh/) as your development environment
2. The `.cursor/rules` directory contains project-specific guidelines for:
   - Code style and best practices
   - Documentation requirements
   - Pull request process
3. These rules will automatically guide Cursor AI when working with the codebase

## How to Contribute

### Reporting Issues

Before creating an issue, please check if a similar issue already exists. When creating a new issue:

1. Use a clear and descriptive title
2. Describe the exact steps to reproduce the issue
3. Explain what behavior you expected and what you observed instead
4. Include relevant logs or screenshots if possible

### Suggesting Features

We love to hear ideas for improving the AI PR Reviewer! When suggesting features:

1. Describe the problem you're trying to solve
2. Explain how your suggestion would solve this problem
3. Provide examples of how the feature would be used

### Pull Requests

Here's how to submit code changes:

1. Fork the repository
2. Create a new branch for your changes
3. Make your changes, following our coding standards
4. Add or update tests for your changes
5. Ensure all tests pass
6. Submit a pull request with a clear description of your changes

### Development Setup

To set up your development environment:

1. Clone the repository
   ```bash
   git clone https://github.com/yourusername/ai-pr-reviewer.git
   cd ai-pr-reviewer
   ```

2. Create a virtual environment
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # For development dependencies
   ```

4. Run tests
   ```bash
   pytest
   ```

## Coding Standards

- Use type hints wherever possible
- Write docstrings for all functions, classes, and modules
- Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guidelines
- Include unit tests for new code

## Adding Support for New AI Providers

To add support for a new AI provider:

1. Update the `ModelAdapter` class in `src/model_adapters.py`
2. Add provider-specific API call logic
3. Update the documentation with the new provider details
4. Add tests for the new provider

## Documentation

When making changes, please update the documentation accordingly:

- Update the README.md if you've changed user-facing functionality
- Add or update docstrings for code changes
- Consider adding examples for new features

## License

By contributing to this project, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).

## Questions?

If you have any questions about contributing, feel free to open an issue with your question or contact the maintainers directly.

Thank you for your contributions!