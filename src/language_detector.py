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
        
        # Special files without extensions
        "package.json": "javascript",
        "composer.json": "php",
        "cargo.toml": "rust",
        "gemfile": "ruby",
        "rakefile": "ruby",
        "requirements.txt": "python",
        "setup.py": "python",
        "pyproject.toml": "python",
        "build.gradle": "java",
        "pom.xml": "java",
        "go.mod": "go",
        "go.sum": "go",
        ".gitignore": "gitignore",
        ".babelrc": "javascript",
        ".eslintrc": "javascript",
        ".prettierrc": "javascript",
    }
    
    # Language-specific patterns for security and bug detection
    LANGUAGE_PATTERNS = {
        "python": {
            "sql_injection": [
                r'execute\(\s*f["\']',  # f-string in SQL execution
                r'execute\(\s*".*?\%.*?"',  # % string formatting in SQL
                r'execute\(\s*".*?\{.*?\}.*?"\.format',  # .format() in SQL
                r'cursor\.execute\(\s*[\'"][^\'")]*\'\s*\+',  # String concatenation in SQL
                r'raw_sql\s*=',  # Raw SQL assignment
                r'rawQuery\(',  # Raw query execution
            ],
            "command_injection": [
                r'os\.system\(\s*[^)]*\)',
                r'subprocess\.(?:call|run|Popen)\(\s*[^)]*\)',
                r'exec\(\s*[^)]*\)',
                r'eval\(\s*[^)]*\)',
                r'__import__\(\s*[^)]*\)',  # Dynamic imports
                r'globals\(\)\[.*?\]',  # Dynamic code execution
            ],
            "path_traversal": [
                r'open\(\s*[^)]*\)',
                r'os\.path\.join\(\s*[^)]*\)',
                r'pathlib\.Path\(\s*[^)]*\)',
                r'with\s+open\(',  # File operations
                r'os\.makedirs\(',  # Directory creation
                r'shutil\.copy',  # File copying operations
            ],
            "error_handling": [
                r'except\s*:',  # Bare except
                r'except\s+Exception\s*:',  # Too broad exception
                r'pass\s*(\n|$)',  # Empty except block with pass
                r'except.*?:\s*pass',  # Exception with only pass
                r'except[^:]*:\s*return',  # Exception without logging
                r'except[^:]*:\s*print\(',  # Using print in exception
            ],
            "hardcoded_secrets": [
                r'password\s*=\s*["\'][^"\']{8,}["\']',
                r'api_key\s*=\s*["\'][^"\']{8,}["\']',
                r'secret\s*=\s*["\'][^"\']{8,}["\']',
                r'token\s*=\s*["\'][^"\']{8,}["\']',
                r'auth_token\s*=\s*["\'][^"\']{8,}["\']',
                r'credentials\s*=\s*["\'][^"\']{8,}["\']',
                r'bearer\s*=\s*["\'][^"\']{8,}["\']',
            ],
            "performance_issues": [
                r'for\s+.*?\s+in\s+.*?:\s*if\s+',  # Loop with filter (could use comprehension)
                r'\.append\(.*?\)\s+for\s+',  # Building lists in loops
                r'\+\s*=.*?for',  # String concatenation in loops
                r'\.keys\(\).*?for.*?in',  # Unnecessary keys() call
                r'\.items\(\).*?for.*?,.*?in',  # Unnecessary items() call when only keys needed
            ],
        },
        "javascript": {
            "sql_injection": [
                r'\.query\(\s*[\'"`].*?\$\{.*?\}.*?[\'"`]',  # Template literals in SQL
                r'\.query\(\s*[\'"`].*?\+.*?[\'"`]',  # String concatenation in SQL
                r'\.execute\(\s*[\'"`].*?\$\{.*?\}.*?[\'"`]',  # Template literals
                r'database\.run\(',  # Direct database operations
                r'connection\.query\(',  # SQL query execution
            ],
            "command_injection": [
                r'exec\(\s*[^)]*\)',
                r'child_process\.exec\(',
                r'eval\(\s*[^)]*\)',
                r'new\s+Function\(',  # Dynamic function creation
                r'setTimeout\(\s*[\'"`]',  # String-based setTimeout
                r'setInterval\(\s*[\'"`]',  # String-based setInterval
                r'document\.write\(',  # DOM manipulation with user input
            ],
            "path_traversal": [
                r'fs\.read',
                r'fs\.write',
                r'path\.join\(',
                r'fs\.createReadStream\(',
                r'fs\.createWriteStream\(',
                r'require\(\s*[^)]*\)',  # Dynamic requires
            ],
            "error_handling": [
                r'catch\s*\([^)]*\)\s*\{\s*\}',  # Empty catch block
                r'catch\s*\([^)]*\)\s*\{\s*\/\/',  # Catch with only comment
                r'try\s*\{[^}]*\}\s*catch\s*\([^)]*\)\s*\{\s*\}',  # Try with empty catch
                r'\.catch\(\s*\(\)\s*=>\s*\{\s*\}\)',  # Promise with empty catch
            ],
            "hardcoded_secrets": [
                r'password\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'apiKey\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'secret\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'token\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'auth\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'bearer\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
            ],
            "performance_issues": [
                r'for\s*\(.*?\s+in\s+.*?\)',  # For-in loops (consider for-of)
                r'\.indexOf\(.*?\)\s*!==?\s*-1',  # Use includes() instead
                r'\.forEach\(.*?\{.*?return',  # forEach with return (won't work as expected)
                r'createElement\(.*?innerHT',  # Potential XSS with innerHTML
            ],
        },
        "typescript": {
            "sql_injection": [
                r'\.query\(\s*[\'"`].*?\$\{.*?\}.*?[\'"`]',  # Template literals in SQL
                r'\.query\(\s*[\'"`].*?\+.*?[\'"`]',  # String concatenation in SQL
                r'execute\(\s*[\'"`].*?\$\{.*?\}.*?[\'"`]',
                r'executeQuery\(',
            ],
            "command_injection": [
                r'exec\(\s*[^)]*\)',
                r'child_process\.exec\(',
                r'eval\(\s*[^)]*\)',
                r'new\s+Function\(',
                r'window\.eval\(',
            ],
            "path_traversal": [
                r'fs\.read',
                r'fs\.write',
                r'path\.join\(',
                r'fs\.createReadStream\(',
                r'fs\.createWriteStream\(',
                r'require\(\s*[^)]*\)',
            ],
            "error_handling": [
                r'catch\s*\([^)]*\)\s*\{\s*\}',  # Empty catch block
                r'catch\s*\([^)]*\)\s*\{\s*\/\/',  # Catch with only comment
                r'try\s*\{[^}]*\}\s*catch\s*\([^)]*\)\s*\{\s*\}',  # Try with empty catch
                r'\.catch\(\s*\(\)\s*=>\s*\{\s*\}\)',  # Promise with empty catch
                r'catch\s*\(error:\s*any\)',  # Too broad error type
            ],
            "hardcoded_secrets": [
                r'password\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'apiKey\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'secret\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'token\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
                r'auth\s*[:=]\s*[\'"`][^\'"`]{8,}[\'"`]',
            ],
            "type_issues": [
                r'as\s+any',  # Type assertions to any
                r':\s*any\b',  # any type annotations
                r':\s*unknown\b(?!\s*=\s*[^;]+\bas\b)',  # unknown without type assertion
                r'!\.',  # Non-null assertion operator
                r'enum\s+\w+\s*\{[^}]*=.*?=',  # Enums with explicit values
            ],
        },
        "php": {
            "sql_injection": [
                r'\$(?:sql|query)\s*=.*?\$_',  # SQL with user input
                r'mysql_query\(\s*["\'].*?\$',  # mysql_query with variable
                r'mysqli_query\(\s*[^,]+,\s*["\'].*?\$',  # mysqli_query with variable
                r'->query\(\s*["\'].*?\$',  # PDO or similar with variable
                r'\$pdo->prepare\(\s*".*?\$',  # PDO prepare with direct string
            ],
            "command_injection": [
                r'system\(\s*\$',
                r'exec\(\s*\$',
                r'passthru\(\s*\$',
                r'shell_exec\(\s*\$',
                r'`\$',  # Backtick operator with variable
                r'proc_open\(\s*\$',
                r'eval\(\s*\$',  # eval with variable
            ],
            "path_traversal": [
                r'file_get_contents\(\s*\$',
                r'fopen\(\s*\$',
                r'include\(\s*\$',
                r'require\(\s*\$',
                r'include_once\(\s*\$',
                r'require_once\(\s*\$',
            ],
            "error_handling": [
                r'@\w+\(',  # Error suppression operator
                r'catch\s*\(\s*Exception\s*\$',  # Too broad exception catch
                r'catch\s*\([^)]*\)\s*\{\s*\}',  # Empty catch block
                r'try\s*\{[^}]*\}\s*catch\s*\([^)]*\)\s*\{\s*\/\/',  # Catch with only comment
            ],
            "hardcoded_secrets": [
                r'\$(?:password|passwd|pwd)\s*=\s*[\'"][^\'"\$]+[\'"]',
                r'\$(?:apiKey|api_key)\s*=\s*[\'"][^\'"\$]+[\'"]',
                r'\$(?:secret|secret_key)\s*=\s*[\'"][^\'"\$]+[\'"]',
                r'\$(?:token|api_token)\s*=\s*[\'"][^\'"\$]+[\'"]',
            ],
        },
        "java": {
            "sql_injection": [
                r'(?:executeQuery|executeUpdate)\(\s*["\'].*?\s*\+',  # String concatenation in SQL
                r'(?:prepareStatement|createStatement)\(\s*["\'].*?\s*\+',  # String concatenation
                r'setString\(\s*\d+\s*,\s*.*?(?:getParameter|getAttribute)\(',  # Unvalidated input
            ],
            "command_injection": [
                r'Runtime\.getRuntime\(\)\.exec\(',
                r'ProcessBuilder\(',
                r'Process\w*\(',
            ],
            "path_traversal": [
                r'new\s+File\(\s*.*?(?:getParameter|getAttribute)\(',
                r'new\s+FileInputStream\(',
                r'new\s+FileOutputStream\(',
            ],
            "error_handling": [
                r'catch\s*\(\s*Exception\s*\w*\s*\)',  # Too broad exception type
                r'catch\s*\(\s*Throwable\s*\w*\s*\)',  # Too broad exception type
                r'catch\s*\([^)]*\)\s*\{\s*\}',  # Empty catch block
                r'\.printStackTrace\(\)',  # Printing stack trace instead of logging
            ],
            "hardcoded_secrets": [
                r'(?:password|passwd|pwd)\s*=\s*["\'][^\'"\$]+["\']',
                r'(?:apiKey|api_key)\s*=\s*["\'][^\'"\$]+["\']',
                r'(?:secret|secret_key)\s*=\s*["\'][^\'"\$]+["\']',
                r'(?:token|api_token)\s*=\s*["\'][^\'"\$]+["\']',
            ],
        },
        "csharp": {
            "sql_injection": [
                r'new\s+SqlCommand\(\s*["\'].*?\s*\+',  # String concatenation in SQL
                r'ExecuteReader\(\s*["\'].*?\s*\+',  # String concatenation
                r'ExecuteNonQuery\(\s*["\'].*?\s*\+',  # String concatenation
                r'cmd\.CommandText\s*=\s*["\'].*?\s*\+',  # String concatenation
            ],
            "command_injection": [
                r'Process\.Start\(',
                r'ProcessStartInfo\(',
                r'System\.Diagnostics\.Process',
            ],
            "path_traversal": [
                r'File\.(?:ReadAllText|WriteAllText|Open|Create)\(',
                r'Directory\.(?:GetFiles|CreateDirectory|Delete)\(',
                r'Path\.(?:Combine|GetFullPath)\(',
            ],
            "error_handling": [
                r'catch\s*\(\s*Exception\s*\w*\s*\)',  # Too broad exception type
                r'catch\s*\(\s*\)',  # Empty catch
                r'catch\s*\([^)]*\)\s*\{\s*\}',  # Empty catch block
                r'catch\s*\([^)]*\)\s*\{\s*\/\/',  # Catch with only comment
            ],
            "hardcoded_secrets": [
                r'(?:password|passwd|pwd)\s*=\s*["\'][^\'"\$]+["\']',
                r'(?:apiKey|api_key)\s*=\s*["\'][^\'"\$]+["\']',
                r'(?:secret|secret_key)\s*=\s*["\'][^\'"\$]+["\']',
                r'(?:token|api_token)\s*=\s*["\'][^\'"\$]+["\']',
                r'ConnectionString\s*=\s*["\'][^\'"\$]+["\']',
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
        Detect the programming language of a file based on its extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Language name or "unknown" if not detected
            
        Raises:
            LanguageDetectionError: If there's an error during language detection
        """
        try:
            logger.debug(f"Detecting language for file: {file_path}")
            
            # Get the filename and normalize it to lowercase for consistent matching
            filename = os.path.basename(file_path).lower()
            
            # Handle docker-compose files as a special case first
            if filename.startswith("docker-compose") and (filename.endswith(".yml") or filename.endswith(".yaml")):
                return "docker-compose"
            
            # Check if the exact filename is in our known files dictionary
            if filename in self.language_extensions:
                language = self.language_extensions[filename]
                logger.debug(f"Detected language for {file_path} by exact filename match: {language}")
                return language
                
            # Special case for Dockerfile
            if filename == "dockerfile" or file_path.lower().endswith("dockerfile"):
                return "dockerfile"
            
            # For files with extensions, check by extension
            _, ext = os.path.splitext(file_path)
            ext = ext.lower()  # Normalize extension to lowercase
            
            if ext in self.language_extensions:
                language = self.language_extensions[ext]
                logger.debug(f"Detected language for {file_path} by extension: {language}")
                return language
            
            # If we get here, try to identify by filename patterns
            if filename.endswith("rc"):  # Common for config files like .babelrc, .eslintrc
                if "babel" in filename:
                    return "javascript"
                elif "eslint" in filename:
                    return "javascript"
                elif "prettier" in filename:
                    return "javascript"
            
            # Return unknown if no match found
            logger.warning(f"Could not detect language for file: {file_path}")
            return "unknown"
            
        except Exception as e:
            logger.error(f"Error detecting language for {file_path}: {str(e)}")
            raise LanguageDetectionError(f"Failed to detect language: {str(e)}", file_path)

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