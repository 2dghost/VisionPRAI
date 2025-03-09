"""
Custom exceptions for the Vision PR AI project.
Provides centralized error definitions with error codes for easier debugging.
"""

from typing import Optional


class VisionPRAIError(Exception):
    """Base exception class for all Vision PR AI errors."""
    
    def __init__(self, message: str, error_code: int):
        """
        Initialize the base exception.
        
        Args:
            message: Descriptive error message
            error_code: Numeric error code identifying the error type
        """
        self.error_code = error_code
        self.message = message
        super().__init__(f"[Error {error_code}] {message}")


# Configuration Errors (1000-1999)
class ConfigurationError(VisionPRAIError):
    """Base class for configuration related errors."""
    
    def __init__(self, message: str, error_code: int = 1000):
        super().__init__(message, error_code)


class MissingConfigurationError(ConfigurationError):
    """Error raised when a required configuration is missing."""
    
    def __init__(self, config_key: str, error_code: int = 1001):
        super().__init__(f"Missing required configuration: {config_key}", error_code)


class InvalidConfigurationError(ConfigurationError):
    """Error raised when a configuration value is invalid."""
    
    def __init__(self, config_key: str, reason: str, error_code: int = 1002):
        super().__init__(f"Invalid configuration value for {config_key}: {reason}", error_code)


# API Errors (2000-2999)
class APIError(VisionPRAIError):
    """Base class for API related errors."""
    
    def __init__(self, message: str, error_code: int = 2000, 
                 status_code: Optional[int] = None, response_text: Optional[str] = None):
        self.status_code = status_code
        self.response_text = response_text
        details = f" (Status: {status_code})" if status_code else ""
        super().__init__(f"{message}{details}", error_code)


class GitHubAPIError(APIError):
    """Error raised when a GitHub API call fails."""
    
    def __init__(self, endpoint: str, status_code: Optional[int] = None, 
                 response_text: Optional[str] = None, error_code: int = 2001):
        super().__init__(
            f"GitHub API error calling {endpoint}",
            error_code,
            status_code,
            response_text
        )


class AIProviderAPIError(APIError):
    """Error raised when an AI provider API call fails."""
    
    def __init__(self, provider: str, status_code: Optional[int] = None, 
                 response_text: Optional[str] = None, error_code: int = 2002):
        super().__init__(
            f"{provider} API error",
            error_code,
            status_code,
            response_text
        )


# Authentication Errors (3000-3999)
class AuthenticationError(VisionPRAIError):
    """Base class for authentication related errors."""
    
    def __init__(self, message: str, error_code: int = 3000):
        super().__init__(message, error_code)


class MissingAPIKeyError(AuthenticationError):
    """Error raised when an API key is missing."""
    
    def __init__(self, provider: str, error_code: int = 3001):
        super().__init__(f"API key for {provider} not found in config or environment variables", error_code)


class InvalidAPIKeyError(AuthenticationError):
    """Error raised when an API key is invalid."""
    
    def __init__(self, provider: str, error_code: int = 3002):
        super().__init__(f"Invalid API key for {provider}", error_code)


# Content Processing Errors (4000-4999)
class ContentProcessingError(VisionPRAIError):
    """Base class for content processing related errors."""
    
    def __init__(self, message: str, error_code: int = 4000):
        super().__init__(message, error_code)


class DiffParsingError(ContentProcessingError):
    """Error raised when parsing a diff fails."""
    
    def __init__(self, reason: str, error_code: int = 4001):
        super().__init__(f"Failed to parse diff: {reason}", error_code)


class ReviewGenerationError(ContentProcessingError):
    """Error raised when generating a review fails."""
    
    def __init__(self, reason: str, error_code: int = 4002):
        super().__init__(f"Failed to generate review: {reason}", error_code)


class CommentExtractionError(ContentProcessingError):
    """Error raised when extracting comments from a review fails."""
    
    def __init__(self, reason: str, error_code: int = 4003):
        super().__init__(f"Failed to extract comments: {reason}", error_code)


# Resource Errors (5000-5999)
class ResourceError(VisionPRAIError):
    """Base class for resource related errors."""
    
    def __init__(self, message: str, error_code: int = 5000):
        super().__init__(message, error_code)


class UnsupportedProviderError(ResourceError):
    """Error raised when an unsupported provider is requested."""
    
    def __init__(self, provider: str, error_code: int = 5001):
        super().__init__(f"Unsupported provider: {provider}", error_code)


class ModelNotAvailableError(ResourceError):
    """Error raised when a requested model is not available."""
    
    def __init__(self, provider: str, model: str, error_code: int = 5002):
        super().__init__(f"Model {model} not available for provider {provider}", error_code)