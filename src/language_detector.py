#!/usr/bin/env python3
"""
Language detection module for the AI PR Reviewer.
Provides functionality to detect programming languages and apply language-specific patterns.
"""

import os
import re
import logging
from typing import Dict, List, Optional, Set, Tuple, Any

try:
    # Try direct imports first (for GitHub Actions and package usage)
    from logging_config import get_logger, with_context
    from custom_exceptions import LanguageDetectionError
except ImportError:
    # Fall back to src-prefixed imports (for local development)
    from src.logging_config import get_logger, with_context
    from src.custom_exceptions import LanguageDetectionError

# Set up logger
logger = get_logger(__name__)


class LanguageDetector:
    """
    A class to detect programming languages and apply language-specific patterns.
    """

    # Common file extensions mapped to programming languages
    LANGUAGE_EXTENSIONS = {
        # Python
        ".py": "python",
        ".pyi": "python",
        ".pyx": "python",
        ".pyw": "python",
        
        # JavaScript
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        
        # TypeScript
        ".ts": "typescript",
        ".tsx": "typescript",
        
        # Java
        ".java": "java",
        
        # C/C++
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cc": "cpp",
        ".hh": "cpp",
        ".cxx": "cpp",
        
        # C#
        ".cs": "csharp",
        
        # Go
        ".go": "go",
        
        # Ruby
        ".rb": "ruby",
        ".erb": "ruby",
        
        # PHP
        ".php": "php",
        
        # Swift
        ".swift": "swift",
        
        # Kotlin
        ".kt": "kotlin",
        ".kts": "kotlin",
        
        # Rust
        ".rs": "rust",
        
        # Scala
        ".scala": "scala",
        
        # Shell
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
        
        # HTML/CSS
        ".html": "html",
        ".htm": "html",
        ".css": "css",
        ".scss": "css",
        ".sass": "css",
        ".less": "css",
        
        # JSON/YAML
        ".json": "json",
        ".yml": "yaml",
        ".yaml": "yaml",
        
        # SQL
        ".sql": "sql",
        
        # Markdown
        ".md": "markdown",
        ".markdown": "markdown",
        
        # XML
        ".xml": "xml",
        
        # Configuration
        ".toml": "toml",
        ".ini": "ini",
        ".cfg": "ini",
        ".conf": "ini",
        
        # Other
        ".dockerfile": "dockerfile",
        "Dockerfile": "dockerfile",
    }
    
    # Language-specific patterns for security and bug detection
    LANGUAGE_PATTERNS = {
        "python": {
            "sql_injection": [
                r'execute\(\s*f["\']',  # f-string in SQL execution
                r'execute\(\s*".*?\%.*?"',  # % string formatting in SQL
                r'execute\(\s*".*?\{.*?\}.*?"\.format',  # .format() in SQL
                r'cursor\.execute\(\s*[\'"][^\'")]*\'\s*\+',  # String concatenation in SQL
            ],
            "command_injection": [
                r'os\.system\(\s*[^)]*\)',
                r'subprocess\.(?:call|run|Popen)\(\s*[^)]*\)',
                r'exec\(\s*[^)]*\)',
                r'eval\(\s*[^)]*\)',
            ],
            "path_traversal": [
                r'open\(\s*[^)]*\)',
                r'os\.path\.join\(\s*[^)]*\)',
                r'pathlib\.Path\(\s*[^)]*\)',
            ],
            "error_handling": [
                r'except\s*:',  # Bare except
                r'except\s+Exception\s*:',  # Too broad exception
                r'pass\s*(\n|$)',  # Empty except block with pass
            ],
            "hardcoded_secrets": [
                r'password\s*=\s*["\'][^"\']{8,}["\']',
                r'api_key\s*=\s*["\'][^"\']{8,}["\']',
                r'secret\s*=\s*["\'][^"\']{8,}["\']',
                r'token\s*=\s*["\'][^"\']{8,}["\']',
            ],
        },
        "javascript": {
            "sql_injection": [
                r'\.query\(\s*[\'"`].*?\$\{.*?\}.*?[\'"`]',  # Template literals in SQL
                r'\.query\(\s*[\'"`].*?\+.*?[\'"`]',  # String concatenation in SQL
            ],
            "command_injection": [
                r'eval\(\s*[^)]*\)',
                r'exec\(\s*[^)]*\)',
                r'child_process\.exec\(\s*[^)]*\)',
                r'new Function\(\s*[^)]*\)',
            ],
            "path_traversal": [
                r'fs\.(?:readFile|writeFile|readFileSync|writeFileSync)\(\s*[^)]*\)',
                r'path\.(?:join|resolve)\(\s*[^)]*\)',
            ],
            "error_handling": [
                r'catch\s*\(\s*\)\s*\{',  # Empty catch parameter
                r'catch\s*\(\s*e\s*\)\s*\{\s*\}',  # Empty catch block
            ],
            "hardcoded_secrets": [
                r'password\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'apiKey\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'secret\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'token\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
            ],
        },
        "typescript": {
            "sql_injection": [
                r'\.query\(\s*[\'"`].*?\$\{.*?\}.*?[\'"`]',  # Template literals in SQL
                r'\.query\(\s*[\'"`].*?\+.*?[\'"`]',  # String concatenation in SQL
            ],
            "command_injection": [
                r'eval\(\s*[^)]*\)',
                r'exec\(\s*[^)]*\)',
                r'child_process\.exec\(\s*[^)]*\)',
                r'new Function\(\s*[^)]*\)',
            ],
            "path_traversal": [
                r'fs\.(?:readFile|writeFile|readFileSync|writeFileSync)\(\s*[^)]*\)',
                r'path\.(?:join|resolve)\(\s*[^)]*\)',
            ],
            "error_handling": [
                r'catch\s*\(\s*\)\s*\{',  # Empty catch parameter
                r'catch\s*\(\s*e\s*\)\s*\{\s*\}',  # Empty catch block
            ],
            "hardcoded_secrets": [
                r'password\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'apiKey\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'secret\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'token\s*[=:]\s*[\'"`][^\'"`]{8,}[\'"`]',
            ],
        },
        "java": {
            "sql_injection": [
                r'executeQuery\(\s*[\'"].*?\+.*?[\'"]',  # String concatenation in SQL
                r'prepareStatement\(\s*[\'"].*?\+.*?[\'"]',  # String concatenation in SQL
            ],
            "command_injection": [
                r'Runtime\.getRuntime\(\)\.exec\(\s*[^)]*\)',
                r'ProcessBuilder\(\s*[^)]*\)',
            ],
            "path_traversal": [
                r'new File\(\s*[^)]*\)',
                r'Paths\.get\(\s*[^)]*\)',
            ],
            "error_handling": [
                r'catch\s*\(\s*Exception\s+e\s*\)',  # Too broad exception
                r'catch\s*\(\s*Throwable\s+[^)]*\)',  # Too broad exception
                r'catch\s*\(\s*[^)]*\)\s*\{\s*\}',  # Empty catch block
            ],
            "hardcoded_secrets": [
                r'password\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
                r'apiKey\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
                r'secret\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
                r'token\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
            ],
        },
        "csharp": {
            "sql_injection": [
                r'ExecuteReader\(\s*[\'"].*?\+.*?[\'"]',  # String concatenation in SQL
                r'ExecuteNonQuery\(\s*[\'"].*?\+.*?[\'"]',  # String concatenation in SQL
                r'string\.Format\(\s*[\'"].*?SELECT.*?[\'"]',  # string.Format in SQL
                r'\$".*?SELECT.*?"',  # String interpolation in SQL
            ],
            "command_injection": [
                r'Process\.Start\(\s*[^)]*\)',
                r'System\.Diagnostics\.Process\.Start\(\s*[^)]*\)',
            ],
            "path_traversal": [
                r'File\.(?:ReadAllText|WriteAllText|Open)\(\s*[^)]*\)',
                r'Directory\.(?:GetFiles|CreateDirectory)\(\s*[^)]*\)',
                r'Path\.(?:Combine|GetFullPath)\(\s*[^)]*\)',
            ],
            "error_handling": [
                r'catch\s*\(\s*Exception\s+[^)]*\)',  # Too broad exception
                r'catch\s*\(\s*\)\s*\{',  # Empty catch parameter
                r'catch\s*\{\s*\}',  # Empty catch block
            ],
            "hardcoded_secrets": [
                r'password\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
                r'apiKey\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
                r'secret\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
                r'token\s*=\s*[\'"][^\'"\;]{8,}[\'"]',
            ],
        },
        # Default patterns to use when language-specific patterns are not available
        "default": {
            "sql_injection": [
                r'(?i)SELECT.*?FROM.*?WHERE.*?\+',  # String concatenation in SQL
                r'(?i)INSERT.*?INTO.*?VALUES.*?\+',  # String concatenation in SQL
                r'(?i)UPDATE.*?SET.*?WHERE.*?\+',  # String concatenation in SQL
                r'(?i)DELETE.*?FROM.*?WHERE.*?\+',  # String concatenation in SQL
            ],
            "command_injection": [
                r'(?i)exec\(',
                r'(?i)system\(',
                r'(?i)shell\(',
                r'(?i)process\(',
            ],
            "path_traversal": [
                r'(?i)\/\.\.\/',  # Path traversal with /../
                r'(?i)\\\.\.\\',  # Path traversal with \..\ (Windows)
                r'(?i)open\(\s*[\'"][^\'"]*[\'"]',  # Open file
            ],
            "error_handling": [
                r'(?i)catch\s*\([^)]*\)\s*\{\s*\}',  # Empty catch
                r'(?i)try\s*\{[^}]*\}\s*catch\s*\{',  # Empty catch
            ],
            "hardcoded_secrets": [
                r'(?i)password\s*[\:\=]\s*[\'"][^\'"\;]{8,}[\'"]',
                r'(?i)api_?key\s*[\:\=]\s*[\'"][^\'"\;]{8,}[\'"]',
                r'(?i)secret\s*[\:\=]\s*[\'"][^\'"\;]{8,}[\'"]',
                r'(?i)token\s*[\:\=]\s*[\'"][^\'"\;]{8,}[\'"]',
            ],
        }
    }

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the LanguageDetector.
        
        Args:
            config_path: Path to the configuration file
        """
        self.logger = get_logger(__name__)
        self.config_path = config_path
        self.logger.debug("LanguageDetector initialized")
        
        # Load custom language extensions from config (if available)
        self.custom_extensions = {}
        self._load_custom_extensions()
        
        # Merge custom extensions with default ones
        self.language_extensions = {**self.LANGUAGE_EXTENSIONS, **self.custom_extensions}
        
        # Compile regex patterns for performance
        self.compiled_patterns = self._compile_patterns()

    @with_context
    def _load_custom_extensions(self) -> None:
        """
        Load custom language extensions from configuration.
        """
        try:
            import yaml
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f)
                
                if config and isinstance(config, dict):
                    language_config = config.get("language_detection", {})
                    custom_extensions = language_config.get("custom_extensions", {})
                    
                    if isinstance(custom_extensions, dict):
                        self.custom_extensions = custom_extensions
                        self.logger.debug("Loaded custom language extensions", 
                                         context={"count": len(custom_extensions)})
        except Exception as e:
            self.logger.warning(f"Error loading custom language extensions: {str(e)}")
    
    @with_context
    def _compile_patterns(self) -> Dict[str, Dict[str, List[re.Pattern]]]:
        """
        Compile regex patterns for performance.
        
        Returns:
            Dictionary of compiled regex patterns
        """
        compiled = {}
        for language, categories in self.LANGUAGE_PATTERNS.items():
            compiled[language] = {}
            for category, patterns in categories.items():
                compiled[language][category] = [re.compile(pattern) for pattern in patterns]
        
        return compiled

    @with_context
    def detect_language(self, file_path: str) -> str:
        """
        Detect programming language based on file extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Detected programming language or "unknown"
        """
        # Extract the file extension
        _, ext = os.path.splitext(file_path)
        
        # Handle files like Dockerfile that don't have a standard extension
        filename = os.path.basename(file_path)
        
        if ext.lower() in self.language_extensions:
            language = self.language_extensions[ext.lower()]
            self.logger.debug(f"Detected language for {file_path}: {language}",
                             context={"file": file_path, "language": language})
            return language
        elif filename in self.language_extensions:
            language = self.language_extensions[filename]
            self.logger.debug(f"Detected language for {file_path}: {language}",
                             context={"file": file_path, "language": language})
            return language
        else:
            self.logger.debug(f"Unknown language for {file_path}",
                             context={"file": file_path, "extension": ext})
            return "unknown"

    @with_context
    def get_language_patterns(self, language: str) -> Dict[str, List[re.Pattern]]:
        """
        Get language-specific patterns for a given language.
        
        Args:
            language: The programming language
            
        Returns:
            Dictionary of compiled regex patterns for the language
        """
        if language in self.compiled_patterns:
            return self.compiled_patterns[language]
        else:
            # Fall back to default patterns if language-specific ones are not available
            self.logger.debug(f"No specific patterns for {language}, using default patterns")
            return self.compiled_patterns["default"]

    @with_context
    def detect_issues(self, file_path: str, file_content: str) -> Dict[str, List[Tuple[int, str]]]:
        """
        Detect potential issues in a file using language-specific patterns.
        
        Args:
            file_path: Path to the file
            file_content: Content of the file
            
        Returns:
            Dictionary of detected issues by category, each with line number and matched text
        """
        language = self.detect_language(file_path)
        patterns = self.get_language_patterns(language)
        
        issues = {}
        lines = file_content.split('\n')
        
        for category, compiled_patterns in patterns.items():
            category_issues = []
            
            for i, line in enumerate(lines, start=1):
                for pattern in compiled_patterns:
                    matches = pattern.findall(line)
                    if matches:
                        category_issues.append((i, line.strip()))
            
            if category_issues:
                issues[category] = category_issues
        
        self.logger.debug(f"Detected {sum(len(v) for v in issues.values())} potential issues in {file_path}",
                         context={"file": file_path, "language": language, 
                                 "issue_count": sum(len(v) for v in issues.values())})
        
        return issues


# Module-level functions for easy access
def detect_language(file_path: str) -> str:
    """
    Detect programming language for a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Detected programming language or "unknown"
    """
    detector = LanguageDetector()
    return detector.detect_language(file_path)


def detect_issues(file_path: str, file_content: str) -> Dict[str, List[Tuple[int, str]]]:
    """
    Detect potential issues in a file.
    
    Args:
        file_path: Path to the file
        file_content: Content of the file
        
    Returns:
        Dictionary of detected issues by category, each with line number and matched text
    """
    detector = LanguageDetector()
    return detector.detect_issues(file_path, file_content) 