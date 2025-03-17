#!/usr/bin/env python3
"""
Main script for the AI PR Reviewer.
Fetches PR details, analyzes with an AI model, and posts review comments.
"""

import os
import sys
import argparse
import json
import logging
import re
import yaml
from typing import Dict, List, Optional, Any, Tuple
import time
import requests
from datetime import datetime

import sys
import os

# Add the parent directory to sys.path to support both local and GitHub Actions environments
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    # Try direct imports first (for GitHub Actions and package usage)
    from model_adapters import ModelAdapter
    from utils import (
        get_pr_diff,
        get_pr_files,
        post_review_comment,
        post_review_sections,
        post_line_comments,
        parse_diff_for_lines,
        extract_code_blocks
    )
    from comment_extractor import CommentExtractor
    from file_filter import FileFilter
    from language_detector import LanguageDetector, detect_language, detect_issues
    from custom_exceptions import (
        VisionPRAIError,
        ConfigurationError,
        MissingConfigurationError,
        InvalidConfigurationError,
        CommentExtractionError,
        LanguageDetectionError
    )
    from logging_config import get_logger, with_context
except ImportError:
    # Fall back to src-prefixed imports (for local development)
    from src.model_adapters import ModelAdapter
    from src.utils import (
        get_pr_diff,
        get_pr_files,
        post_review_comment,
        post_review_sections,
        post_line_comments,
        parse_diff_for_lines,
        extract_code_blocks
    )
    from src.comment_extractor import CommentExtractor
    from src.file_filter import FileFilter
    from src.language_detector import LanguageDetector, detect_language, detect_issues
    from src.custom_exceptions import (
        VisionPRAIError,
        ConfigurationError,
        MissingConfigurationError, 
        InvalidConfigurationError,
        CommentExtractionError,
        LanguageDetectionError
    )
    from src.logging_config import get_logger, with_context

# Get structured logger
logger = get_logger("ai-pr-reviewer")


@with_context
def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    Load configuration from a YAML file and merge with cursor rules.
    
    Args:
        config_path: Path to the config file
        
    Returns:
        Dictionary containing configuration
        
    Raises:
        MissingConfigurationError: If the config file does not exist
        InvalidConfigurationError: If the config file is not valid YAML or missing required fields
    """
    # Validate the config path
    if not os.path.exists(config_path):
        logger.error(f"Config file not found: {config_path}", 
                    context={"config_path": config_path})
        raise MissingConfigurationError("config_file")
    
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse YAML in config file: {e}",
                    context={"config_path": config_path, "error": str(e)})
        raise InvalidConfigurationError("config_file", f"Invalid YAML format: {e}")
    
    # Load cursor rules if they exist
    cursor_rules_path = os.path.join(os.getcwd(), ".cursor", "rules")
    if os.path.exists(cursor_rules_path):
        logger.info("Loading cursor rules", context={"rules_path": cursor_rules_path})
        try:
            rules = {}
            for rule_file in os.listdir(cursor_rules_path):
                if rule_file.endswith(".mdc"):
                    with open(os.path.join(cursor_rules_path, rule_file), "r") as f:
                        rule_content = f.read()
                        rules[rule_file[:-4]] = rule_content  # Remove .mdc extension
            
            # Add cursor rules to config
            if rules:
                config["cursor_rules"] = rules
                logger.info("Successfully loaded cursor rules", 
                           context={"rules_count": len(rules)})
        except Exception as e:
            logger.warning(f"Failed to load cursor rules: {e}",
                         context={"error": str(e)})
    
    # Validate minimum required configuration
    if not config:
        logger.error("Config file is empty or not valid YAML",
                    context={"config_path": config_path})
        raise InvalidConfigurationError("config_file", "Empty or invalid YAML")
        
    if "model" not in config:
        logger.error("Missing required 'model' section in config",
                    context={"config_path": config_path})
        raise MissingConfigurationError("model")
    
    # Check for required model configuration
    model_config = config.get("model", {})
    required_fields = ["provider", "endpoint", "model"]
    missing_fields = [field for field in required_fields if field not in model_config]
    
    if missing_fields:
        missing_fields_str = ", ".join(missing_fields)
        logger.error(f"Missing required fields in model config: {missing_fields_str}",
                    context={"config_path": config_path, "missing_fields": missing_fields})
        raise MissingConfigurationError(f"model.{missing_fields[0]}" if missing_fields else "model")
    
    logger.debug("Successfully loaded configuration", 
                context={"config_path": config_path, "provider": model_config.get("provider")})
    return config


@with_context
def get_environment_variables() -> Tuple[str, str, str]:
    """
    Get required environment variables.
    
    Returns:
        Tuple of (github_token, repo, pr_number)
        
    Raises:
        MissingConfigurationError: If required environment variables are missing
    """
    # Get GitHub token from environment or config
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        logger.error("GITHUB_TOKEN environment variable is required")
        raise MissingConfigurationError("GITHUB_TOKEN")
    
    # Debug log all environment variables related to GitHub events
    logger.debug("Environment variables:")
    for key in sorted(os.environ.keys()):
        if "GITHUB" in key:
            # Mask token values for security
            value = os.environ[key]
            if "TOKEN" in key:
                value = "***" if value else "not set"
            logger.debug(f"  {key}: {value}")
        
    # Get repository and PR number
    if "GITHUB_REPOSITORY" in os.environ and "GITHUB_EVENT_NUMBER" in os.environ:
        # Running in GitHub Actions
        repo = os.environ["GITHUB_REPOSITORY"]
        pr_number = os.environ["GITHUB_EVENT_NUMBER"]
        logger.info(f"Running in GitHub Actions environment (repo: {repo}, PR #: {pr_number})")
    else:
        # Running locally
        repo = os.environ.get("PR_REPOSITORY")
        pr_number = os.environ.get("PR_NUMBER")
        
        if not repo or not pr_number:
            missing_vars = []
            if not repo:
                missing_vars.append("PR_REPOSITORY")
            if not pr_number:
                missing_vars.append("PR_NUMBER")
                
            error_msg = "When running locally, PR_REPOSITORY and PR_NUMBER environment variables are required"
            logger.error(error_msg, context={"missing_variables": missing_vars})
            raise MissingConfigurationError(missing_vars[0] if missing_vars else "PR_REPOSITORY")
        
        logger.debug("Running in local environment", 
                    context={"repo": repo, "pr_number": pr_number})
            
    return github_token, repo, pr_number


@with_context
def generate_prompt(diff: str, files: List[Dict[str, Any]], config: Dict[str, Any]) -> str:
    """
    Generate a prompt for the AI model.
    
    Args:
        diff: The PR diff
        files: List of files changed in the PR (after filtering)
        config: Configuration dictionary
        
    Returns:
        Prompt for the AI model
    """
    # Get focus areas from config
    focus_areas = config.get("review", {}).get("focus_areas", "")
    
    # Get cursor rules if available
    cursor_rules = config.get("cursor_rules", {})
    
    # Check if file filtering is enabled
    file_filtering_enabled = config.get("review", {}).get("file_filtering", {}).get("enabled", False)
    exclude_patterns = config.get("review", {}).get("file_filtering", {}).get("exclude_patterns", [])
    
    # Check if language detection is enabled
    language_detection_enabled = config.get("review", {}).get("language_detection", {}).get("enabled", False)
    
    # Get review format settings
    format_config = config.get("review", {}).get("format", {})
    include_summary = format_config.get("include_summary", True)
    include_overview = format_config.get("include_overview", True)
    include_recommendations = format_config.get("include_recommendations", True)
    template_style = format_config.get("template_style", "default")
    split_comments = format_config.get("split_comments", False)
    
    # Extract relevant file info
    file_info = []
    
    # If language detection is enabled, add language information to file info
    if language_detection_enabled:
        language_detector = LanguageDetector(config_path=config.get("config_path", "config.yaml"))
        
        for file in files:
            language = language_detector.detect_language(file["filename"])
            file_info_entry = {
                "filename": file["filename"],
                "status": file["status"],
                "additions": file["additions"],
                "deletions": file["deletions"],
                "changes": file["changes"],
                "language": language
            }
            
            # Only add detailed language analysis for non-binary files that can be analyzed
            if file.get("patch") and language != "unknown":
                try:
                    # Extract code from the patch
                    code_content = file.get("patch", "")
                    # Detect potential issues
                    detected_issues = language_detector.detect_issues(file["filename"], code_content)
                    
                    # Only add if there are issues
                    if detected_issues:
                        file_info_entry["potential_issues"] = {}
                        for category, issues in detected_issues.items():
                            issue_count = len(issues)
                            if issue_count > 0:
                                file_info_entry["potential_issues"][category] = issue_count
                except Exception as e:
                    logger.warning(f"Error detecting issues in {file['filename']}: {str(e)}")
            
            file_info.append(file_info_entry)
    else:
        # Default file info without language detection
        for file in files:
            file_info.append({
                "filename": file["filename"],
                "status": file["status"],
                "additions": file["additions"],
                "deletions": file["deletions"],
                "changes": file["changes"]
            })
    
    # Create a comprehensive prompt
    prompt = (
        "You are an expert code reviewer following best practices. "
        "Analyze this PR diff and provide detailed, constructive feedback with concrete code improvements.\n"
        f"{focus_areas}\n\n"
    )
    
    # Add language-specific guidance if language detection is enabled
    if language_detection_enabled and file_info:
        # Collect detected languages
        languages = set()
        for file in file_info:
            if "language" in file and file["language"] != "unknown":
                languages.add(file["language"])
                
        # Add language-specific guidance section to the prompt
        if languages:
            prompt += "## Language-Specific Guidance\n\n"
            
            for language in sorted(languages):
                if language == "python":
                    prompt += "### Python Best Practices\n"
                    prompt += "- Use type hints for better maintainability and IDE support\n"
                    prompt += "- Prefer context managers (with statements) for resource management\n"
                    prompt += "- Use f-strings instead of older string formatting methods\n"
                    prompt += "- Follow PEP 8 style guidelines\n"
                    prompt += "- Use specific exception types rather than generic Exception or bare except\n"
                    prompt += "- Validate user inputs before using in SQL queries to prevent injection\n\n"
                elif language == "javascript" or language == "typescript":
                    prompt += f"### {language.capitalize()} Best Practices\n"
                    prompt += "- Prefer const and let over var\n"
                    prompt += "- Use === instead of == for comparisons\n"
                    prompt += "- Validate user inputs before adding to DOM or using in queries\n"
                    prompt += "- Avoid direct DOM manipulation when using frameworks\n"
                    prompt += "- Use async/await instead of raw Promises when possible\n"
                    if language == "typescript":
                        prompt += "- Avoid using 'any' type except when absolutely necessary\n"
                        prompt += "- Prefer interfaces for object shapes over type aliases\n"
                        prompt += "- Use non-null assertion operator (!.) sparingly\n"
                    prompt += "\n"
                elif language == "java":
                    prompt += "### Java Best Practices\n"
                    prompt += "- Use try-with-resources for AutoCloseable resources\n"
                    prompt += "- Prefer prepared statements for SQL queries\n"
                    prompt += "- Follow standard naming conventions (camelCase for methods/variables)\n"
                    prompt += "- Properly handle exceptions with specific catch blocks\n"
                    prompt += "- Use StringBuilder for string concatenation in loops\n\n"
                elif language == "csharp":
                    prompt += "### C# Best Practices\n"
                    prompt += "- Use 'using' statements for IDisposable resources\n"
                    prompt += "- Prefer async/await over Task.Continue patterns\n"
                    prompt += "- Use parameterized queries for database operations\n"
                    prompt += "- Prefer properties over public fields\n"
                    prompt += "- Follow standard naming conventions (PascalCase for public members)\n\n"
                elif language == "php":
                    prompt += "### PHP Best Practices\n"
                    prompt += "- Use prepared statements for SQL queries\n"
                    prompt += "- Always validate and sanitize user input\n"
                    prompt += "- Follow PSR standards for code formatting\n"
                    prompt += "- Use type declarations (PHP 7+)\n"
                    prompt += "- Avoid using the @ error suppression operator\n\n"
                elif language == "go":
                    prompt += "### Go Best Practices\n"
                    prompt += "- Handle errors explicitly, don't use _ to ignore them\n"
                    prompt += "- Use context for cancellation and timeouts\n"
                    prompt += "- Follow Go's standard formatting (gofmt)\n"
                    prompt += "- Prefer composition over inheritance\n"
                    prompt += "- Use meaningful variable names (not single letters)\n\n"
            
            prompt += "\n"
    
    prompt += (
        "CRITICAL: For each issue, you MUST format your line-specific comments exactly like this:\n\n"
        "### filename.ext:line_number\n"
        "Problem: <clear explanation of the issue>\n\n"
        "```suggestion\n"
        "<exact code that should replace the original code>\n"
        "```\n\n"
        "Explanation: <why this change improves the code, including technical rationale, potential bugs prevented, and relevant best practices>\n\n"
        "Guidelines:\n"
        "1. ALWAYS include the file name and line number in the header (### filename.ext:line_number)\n"
        "2. Each suggestion must be preceded by a clear explanation of the issue\n"
        "3. The suggestion block must contain the complete fixed code\n"
        "4. After each suggestion, provide a DETAILED explanation including:\n"
        "   - Technical reasoning behind the change\n"
        "   - Specific bugs or issues prevented\n"
        "   - How it follows best practices or patterns used elsewhere in the codebase\n"
        "   - Performance, security, or maintainability benefits\n"
        "   - Any relevant documentation or standards that support your suggestion\n"
        "   - Educational explanations of the concepts involved for less experienced developers\n"
        "   - Links to relevant documentation or resources when appropriate\n"
        "   - Alternative approaches that could also solve the issue and their trade-offs\n"
        "5. Make suggestions ONLY for lines that exist in the diff\n"
        "6. If you find ANY issues, you MUST provide at least one code suggestion\n"
        "7. IMPORTANT: Each file-specific comment MUST start with '### filename.ext:line_number' format\n"
        "8. Educational Context: For each issue, explain the underlying programming concepts to help developers learn\n"
        "9. Best Practices References: Cite specific industry standards, style guides, or documentation\n"
        "10. Security Implications: Always highlight security implications when relevant\n"
        "11. Performance Considerations: Include performance impacts of problematic code and improvements\n"
        "12. Alternative Approaches: Provide at least one alternative solution with pros and cons\n"
        "13. Code Quality Metrics: Explain how your suggestion improves maintainability, readability, or testability\n"
        "14. Common Pitfalls: Explain common mistakes related to the issue to help prevent similar problems\n"
        "15. Cross-Language Context: When applicable, compare how similar patterns work in other languages\n"
    )
    
    # Add cursor rules guidance if available
    if cursor_rules:
        prompt += "Follow these project-specific guidelines:\n\n"
        for rule_name, rule_content in cursor_rules.items():
            prompt += f"### {rule_name} Guidelines\n{rule_content}\n\n"
    
    # Add files and diff information
    prompt += (
        f"Files changed in this PR:\n{json.dumps(file_info, indent=2)}\n\n"
        "PR Diff:\n"
        f"```diff\n{diff}\n```\n\n"
    )
    
    # Format instructions - IMPORTANT: Keep the exact format consistent for regex extraction
    prompt += (
        "Your review MUST follow this EXACT format with these EXACT section headers:\n\n"
    )
    
    # Add sections with consistent headers that match our regex patterns
    sections = []
    
    if include_summary:
        sections.append(
            "## Summary\n"
            "Provide a concise summary of the PR, including its purpose and overall quality.\n"
        )
    
    if include_overview:
        sections.append(
            "## Overview of Changes\n"
            "List the key changes and their impact. Highlight any architectural decisions.\n"
        )
    
    # Always include detailed feedback section
    sections.append(
        "## Detailed Feedback\n"
        "Provide detailed analysis of the code changes. Include specific issues and recommendations.\n"
    )
    
    # Add a dedicated section for file-specific comments
    sections.append(
        "## File-Specific Comments\n"
        "Include all line-specific comments here, using the exact format specified above (### filename.ext:line_number).\n"
        "This section MUST contain at least one file-specific comment for each file with issues.\n"
        "IMPORTANT: This section is required and will be used to post comments on specific lines of code.\n"
        "DO NOT provide general recommendations - ONLY specific code changes with file and line references.\n"
        "ENSURE each explanation is detailed and educational, including:\n"
        "- The technical reasoning behind the suggested change\n"
        "- Potential issues or bugs prevented by the change\n"
        "- How the change improves code quality, performance, or security\n"
        "- Any relevant best practices, patterns or standards that support the suggestion\n"
        "- Educational context to help less experienced developers understand WHY the change matters\n"
        "- References to documentation or resources when applicable\n"
        "- Alternative approaches that could also solve the issue with their trade-offs\n"
        "- Examples of how the issue could manifest in production environments\n"
        "- For security issues, explanation of attack vectors and mitigation strategies\n"
    )
    
    if include_recommendations:
        sections.append(
            "## Recommendations\n"
            "IMPORTANT: Do NOT provide general text recommendations here. Instead, for each recommendation:\n"
            "1. Identify the specific file and line number\n"
            "2. Format as '### filename.ext:line_number'\n"
            "3. Explain the issue\n"
            "4. Provide a code suggestion block with the exact code change\n"
            "5. Explain why your solution is better\n"
        )
    
    # Add numbered sections to the prompt
    for i, section in enumerate(sections, 1):
        prompt += f"{i}. {section}"
    
    prompt += (
        "IMPORTANT REMINDERS:\n"
        "- ALWAYS include specific line numbers in the format 'filename.ext:line_number'\n"
        "- Make suggestions ONLY for lines in the diff\n"
        "- Each suggestion must be complete and valid code\n"
        "- If you find ANY issues, you MUST provide at least one code suggestion\n"
        "- Use the EXACT section headers shown above (## Summary, ## Overview of Changes, etc.)\n"
        "- NEVER provide general recommendations without specific code changes\n"
        "- ALL recommendations MUST be in the form of specific code changes with file and line references\n"
        "- Provide comprehensive explanations that help developers learn and improve their coding skills\n"
        "- Include context about why your suggestions follow best practices or improve the codebase\n"
        "- Make your explanations educational for programmers of all skill levels\n"
        "- Include specific examples, not just vague assertions\n"
        "- Cite relevant documentation, standards, or articles when appropriate\n"
        "- For each alternative approach mentioned, explain why you chose your suggested approach\n"
        "- Tailor your explanations to the apparent experience level of the developer\n"
    )
    
    return prompt


@with_context
def get_existing_reviews(repo: str, pr_number: str, token: str) -> List[Dict[str, Any]]:
    """
    Get existing reviews for a PR.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        
    Returns:
        List of existing review data
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    
    try:
        logger.info(f"Fetching existing reviews for PR #{pr_number} in {repo}")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        reviews = response.json()
        
        # Filter only bot reviews (assuming bot uses the GitHub token which shows as GitHub Actions)
        bot_reviews = [
            review for review in reviews 
            if review.get("user", {}).get("login", "") == "github-actions[bot]"
        ]
        
        logger.info(f"Found {len(bot_reviews)} existing bot reviews")
        return bot_reviews
    except Exception as e:
        logger.error(f"Error fetching existing reviews: {str(e)}")
        return []


def get_pr_diff(repo: str, pr_number: str, token: str) -> str:
    """
    Get the diff of a PR from GitHub.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        
    Returns:
        The diff of the PR
    """
    headers = {
        "Accept": "application/vnd.github.v3.diff",
        "Authorization": f"Bearer {token}",  # Use "Bearer" instead of "token"
        "User-Agent": "VisionPRAI"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    
    logger.info(f"Fetching diff for PR #{pr_number} in {repo}")
    logger.debug(f"GitHub API URL: {url}")
    token_preview = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "***"
    logger.debug(f"Using token (preview): {token_preview}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        diff = response.text
        
        # Log response details
        logger.debug(f"Response status code: {response.status_code}")
        logger.debug(f"Response headers: {dict(response.headers)}")
        
        # Debug the retrieved diff
        diff_size = len(diff)
        diff_preview = diff[:500] + "..." if diff_size > 500 else diff
        
        if diff_size == 0:
            logger.error("Retrieved empty diff from GitHub API")
        else:
            logger.info(f"Retrieved diff of size {diff_size} bytes")
            logger.debug(f"Diff preview: {diff_preview}")
            
            # Count files in diff
            file_count = diff.count("diff --git ")
            logger.info(f"Detected {file_count} files in the diff")
            
        return diff
    except Exception as e:
        logger.error(f"Error getting PR diff: {str(e)}")
        if isinstance(e, requests.exceptions.HTTPError) and hasattr(e, 'response'):
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response content: {e.response.text[:500]}")
        return ""


@with_context
def get_pr_files_with_changes(repo: str, pr_number: str, token: str) -> List[Dict[str, Any]]:
    """
    Get the list of files that have been changed in the current push to a PR.
    This is different from get_pr_files, which gets all files in the PR.
    
    For synchronize events, this helps identify which files were changed in this push.
    
    Args:
        repo: Repository in the format 'owner/repo'
        pr_number: Pull request number
        token: GitHub token
        
    Returns:
        List of files that have changes
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "VisionPRAI"
    }
    
    # First, get the PR details to find the latest commit
    pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    logger.info(f"Fetching PR details to get latest commits")
    
    try:
        pr_response = requests.get(pr_url, headers=headers)
        pr_response.raise_for_status()
        pr_data = pr_response.json()
        
        # Extract the latest commit SHA
        head_sha = pr_data.get("head", {}).get("sha")
        if not head_sha:
            logger.error("Failed to get latest commit SHA from PR data")
            return []
            
        logger.info(f"Latest commit SHA for PR: {head_sha}")
        
        # Now get the files changed in this commit
        commit_url = f"https://api.github.com/repos/{repo}/commits/{head_sha}"
        logger.info(f"Fetching files changed in latest commit: {head_sha}")
        
        commit_response = requests.get(commit_url, headers=headers)
        commit_response.raise_for_status()
        commit_data = commit_response.json()
        
        files = commit_data.get("files", [])
        logger.info(f"Found {len(files)} files changed in latest commit")
        
        return files
    except Exception as e:
        logger.error(f"Error getting files changed in latest commit: {str(e)}")
        if isinstance(e, requests.exceptions.HTTPError) and hasattr(e, 'response'):
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response content: {e.response.text[:500]}")
        return []


@with_context
def review_pr(config_path: Optional[str] = None, verbose: bool = False) -> bool:
    """
    Main function to review a pull request.
    
    Args:
        config_path: Path to the config file (default: "config.yaml")
        verbose: Enable verbose logging
        
    Returns:
        True if the review was completed successfully, False otherwise
    """
    if verbose:
        # Update log level in the structured logger
        os.environ["LOG_LEVEL"] = "DEBUG"
    
    try:
        # Load config
        config_file = config_path or "config.yaml"
        logger.info(f"Loading configuration from {config_file}", 
                   context={"config_path": config_file})
        config = load_config(config_file)
        
        # Get environment variables
        logger.info("Retrieving environment variables")
        github_token, repo, pr_number = get_environment_variables()
        
        # Check what kind of event triggered this run
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        event_action = os.environ.get("GITHUB_ACTION", "")
        
        logger.info(f"Event name: {event_name}, Action: {event_action}")
        
        # For synchronize events, we only want to review what changed
        is_synchronize_event = (event_name == "pull_request" and 
                               event_action == "synchronize")
        
        if is_synchronize_event:
            logger.info("This is a synchronize event (new push to PR)")
        
        # Verify token is working by checking rate limit
        try:
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {github_token}",
                "User-Agent": "VisionPRAI"
            }
            rate_limit_url = "https://api.github.com/rate_limit"
            rate_limit_response = requests.get(rate_limit_url, headers=headers)
            rate_limit_response.raise_for_status()
            rate_limit_data = rate_limit_response.json()
            
            remaining = rate_limit_data.get("resources", {}).get("core", {}).get("remaining", "unknown")
            reset_time = rate_limit_data.get("resources", {}).get("core", {}).get("reset", 0)
            reset_datetime = datetime.fromtimestamp(reset_time).strftime("%Y-%m-%d %H:%M:%S") if reset_time else "unknown"
            
            logger.info(f"GitHub API rate limit: {remaining} remaining, resets at {reset_datetime}")
        except Exception as e:
            logger.warning(f"Failed to check GitHub API rate limit: {str(e)}")
            # Continue anyway, as this is just a verification step
        
        # Check for existing reviews to determine our strategy
        existing_reviews = get_existing_reviews(repo, pr_number, github_token)
        is_first_review = len(existing_reviews) == 0
        logger.info(f"Is this the first review of this PR? {is_first_review}")
        
        # Initialize model adapter
        provider = config['model']['provider']
        model_name = config['model']['model']
        logger.info(f"Initializing AI model adapter", 
                   context={"provider": provider, "model": model_name})
        model_config = config.get("model", {})
        model_adapter = ModelAdapter(model_config)
    except VisionPRAIError as e:
        logger.error(f"Configuration error: {e.message}",
                   context={"error_code": e.error_code})
        return False
    except Exception as e:
        logger.error(f"Initialization error: {str(e)}",
                    context={"error_type": type(e).__name__},
                    exc_info=True)
        return False
    
    # Fetch PR diff
    logger.info(f"Fetching diff for PR #{pr_number} in {repo}")
    diff = get_pr_diff(repo, pr_number, github_token)
    if not diff:
        logger.error("No diff found. Exiting.")
        return False
    
    # Fetch PR files
    logger.info(f"Fetching files for PR #{pr_number} in {repo}")
    files = get_pr_files(repo, pr_number, github_token)
    if not files:
        logger.warning("No files found. Continuing with diff only.")
        
    # For synchronize events, try to get just the files that changed in this push
    if is_synchronize_event and files:
        changed_files = get_pr_files_with_changes(repo, pr_number, github_token)
        
        if changed_files:
            logger.info(f"Found {len(changed_files)} files changed in this push")
            # Replace the full files list with just the changed files
            files = changed_files
            logger.info("Will only review files changed in this push")
    
    # Apply file filtering if files were found
    if files:
        logger.info("Applying file filtering rules")
        file_filter = FileFilter(config)
        original_file_count = len(files)
        files = file_filter.filter_files(files)
        
        if file_filter.enabled:
            filtered_count = original_file_count - len(files)
            if filtered_count > 0:
                logger.info(f"Filtered out {filtered_count} files based on configured rules", 
                           context={"original_count": original_file_count, 
                                   "filtered_count": len(files)})
    
    # Generate prompt
    logger.info("Generating prompt for AI review")
    prompt = generate_prompt(diff, files, config)
    
    # Call AI for review
    try:
        logger.info(f"Sending PR to {model_config['provider']} {model_config['model']} for review")
        review_text = model_adapter.generate_response(prompt)
        
        # Log the first part of the response for debugging
        logger.debug(f"AI response first 500 chars: {review_text[:500]}")
        
        # Verify that we received a non-empty response
        if not review_text or len(review_text.strip()) < 10:
            logger.error("Received empty or very short response from AI model")
            return False
    except Exception as e:
        logger.error(f"Error generating review: {str(e)}")
        return False
    
    # Prepare summary overview
    logger.info("Preparing overview comment")
    
    # Extract just summary and overview sections
    summary_pattern = r'(?:^|\n)## Summary\s*\n(.*?)(?=\n##|\Z)'
    overview_pattern = r'(?:^|\n)## Overview of Changes\s*\n(.*?)(?=\n##|\Z)'
    recommendations_pattern = r'(?:^|\n)## Recommendations\s*\n(.*?)(?=\n##|\Z)'
    
    summary_match = re.search(summary_pattern, review_text, re.DOTALL)
    overview_match = re.search(overview_pattern, review_text, re.DOTALL)
    recommendations_match = re.search(recommendations_pattern, review_text, re.DOTALL)
    
    # Log the review text for debugging
    logger.debug(f"Review text received (first 1000 chars): {review_text[:1000]}...")
    logger.debug(f"Review text received (last 1000 chars): {review_text[-1000:]}...")
    
    # Construct the overview text differently based on whether this is the first review
    if is_first_review:
        overview_text = "# AI Review Summary\n\n"
        
        if summary_match:
            overview_text += f"## Summary\n{summary_match.group(1).strip()}\n\n"
            logger.debug("Summary section found and extracted")
        else:
            logger.warning("No summary section found in the review text")
            # Add a fallback summary if none was found
            overview_text += "## Summary\nThis PR contains code changes that have been reviewed by the AI.\n\n"
        
        if overview_match:
            overview_text += f"## Overview of Changes\n{overview_match.group(1).strip()}\n\n"
            logger.debug("Overview section found and extracted")
        else:
            logger.warning("No overview section found in the review text")
            # Add a fallback overview if none was found
            overview_text += "## Overview of Changes\n- Code changes were analyzed\n- See detailed comments for specific feedback\n\n"
        
        if recommendations_match:
            overview_text += f"## Recommendations\n{recommendations_match.group(1).strip()}\n\n"
            logger.debug("Recommendations section found and extracted")
    else:
        # For subsequent reviews, create a more focused update message
        overview_text = f"# AI Review Update\n\n"
        
        if summary_match:
            overview_text += f"## Summary of Changes\n{summary_match.group(1).strip()}\n\n"
        else:
            overview_text += "## Summary of Changes\nI've reviewed the latest changes in this PR.\n\n"
            
        if recommendations_match:
            overview_text += f"## New Recommendations\n{recommendations_match.group(1).strip()}\n\n"
    
    # Add a note about code-specific comments
    overview_text += "\n\n> Detailed feedback has been added as review comments on specific code lines."
    
    # Check if we should post line-specific comments
    line_comments_enabled = config.get("review", {}).get("line_comments", True)
    if line_comments_enabled:
        try:
            logger.info("Processing line-specific comments", 
                       context={"repo": repo, "pr_number": pr_number})
            
            # Parse the diff to map line numbers to positions
            logger.info("Parsing diff to map line numbers to positions in the diff")
            file_line_positions = parse_diff_for_lines(diff)
            
            if not file_line_positions:
                logger.warning("Could not parse any line positions from diff. Review comments may not appear on specific lines.")
            else:
                logger.info(f"Successfully parsed positions for {len(file_line_positions)} files")
            
            # Extract comments from the review
            logger.info("Extracting comments from AI review")
            comment_extractor = CommentExtractor()
            valid_comments = comment_extractor.extract_comments(review_text, file_line_positions)
            
            logger.info(f"Extracted {len(valid_comments)} valid comments from review")
            
            if valid_comments:
                # Log statistics about comments per file
                comments_by_file = {}
                for comment in valid_comments:
                    file_path = comment.get("path", "unknown")
                    if file_path not in comments_by_file:
                        comments_by_file[file_path] = []
                    comments_by_file[file_path].append(comment)
                
                logger.info(f"Comment distribution across {len(comments_by_file)} files:")
                for file_path, comments in comments_by_file.items():
                    logger.info(f"  - {file_path}: {len(comments)} comments")
                
                # Post line comments
                try:
                    logger.info("Posting line comments with overview text (draft review approach)")
                    line_comment_success = post_line_comments(
                        repo, 
                        pr_number, 
                        github_token, 
                        valid_comments,
                        overview_text=review_text  # Pass the review text as the overview
                    )
                    
                    if line_comment_success:
                        logger.info("Successfully posted line comments")
                    else:
                        logger.error("Failed to post line comments")
                except Exception as e:
                    logger.error(f"Error posting line comments: {str(e)}", exc_info=True)
            else:
                logger.warning("No valid comments extracted from review")
        except CommentExtractionError as e:
            logger.error(f"Error extracting line comments: {str(e)}",
                        context={"error_code": e.error_code, "repo": repo, "pr_number": pr_number},
                        exc_info=True)
            # Continue despite errors in line comments
        except Exception as e:
            logger.error(f"Error processing line comments: {str(e)}",
                        context={"repo": repo, "pr_number": pr_number},
                        exc_info=True)
            # Continue despite errors in line comments
    
    logger.info("PR review completed successfully")
    return True


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="AI PR Reviewer")
    parser.add_argument("-c", "--config", help="Path to config file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()
    
    logger.info("=========================================================")
    logger.info("Starting AI PR Review - Triggered by workflow")
    if "GITHUB_EVENT_NAME" in os.environ:
        logger.info(f"Triggered by GitHub event: {os.environ.get('GITHUB_EVENT_NAME')}")
    if "GITHUB_EVENT_ACTION" in os.environ:
        logger.info(f"Event action: {os.environ.get('GITHUB_EVENT_ACTION')}")
    logger.info("=========================================================")
    
    success = review_pr(config_path=args.config, verbose=args.verbose)
    
    if success:
        logger.info("=========================================================")
        logger.info("AI PR Review completed successfully")
        logger.info("=========================================================")
    else:
        logger.error("=========================================================")
        logger.error("AI PR Review failed")
        logger.error("=========================================================")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()