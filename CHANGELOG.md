# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Corrected module import paths in `src/review_pr.py` to use explicit `src.` prefix
- Added missing `re` module import in `src/review_pr.py`
- Changed GitHub token environment variable from `GITHUB_TOKEN` to `GH_TOKEN` across all files
- Improved OpenAI response handling to support different API response formats
- Fixed syntax issue in `pyproject.toml`

### Added
- Created workflow documentation in `.github/workflows/README.md`
- Added troubleshooting section to the main README
- Created this CHANGELOG file

## [0.1.0] - 2024-03-08

### Added
- Initial release
- Support for multiple AI providers (OpenAI, Anthropic, Google, Mistral, Ollama, Hugging Face)
- GitHub Action workflow for automated PR reviews
- Line-specific comments for detailed code feedback
- Configurable review focus areas