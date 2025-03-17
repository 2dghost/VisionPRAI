"""
Model adapter for interfacing with different AI providers.
Provides a unified interface for generating responses from different AI models.
"""

import os
import json
import requests
from typing import Dict, Any, Optional
import logging


class ModelAdapter:
    """A model-agnostic adapter to interface with different AI providers."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the model adapter with configuration.
        
        Args:
            config: Dictionary containing model configuration
                   (provider, api_key, endpoint, model, etc.)
        """
        self.provider = config["provider"].lower()
        logger = logging.getLogger("ai-pr-reviewer")
        logger.info(f"Initializing model adapter for provider: {self.provider}")
        
        # Special handling for Anthropic to prioritize the environment variable
        if self.provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY") or config.get("api_key")
            if os.environ.get("ANTHROPIC_API_KEY"):
                logger.info("Using ANTHROPIC_API_KEY from environment variables")
            else:
                logger.info("ANTHROPIC_API_KEY not found in environment, using config value")
        else:
            api_key = config.get("api_key") or os.environ.get(f"{self.provider.upper()}_API_KEY")
            
        # Ensure API key is trimmed of any whitespace and newlines
        if api_key:
            # Strip all whitespace, newlines, and control characters
            api_key = api_key.strip().replace('\n', '').replace('\r', '')
            logger.debug("Cleaned API key of any whitespace and newline characters")
            
        self.api_key = api_key if api_key else None
        
        # Log API key presence (not the actual key)
        if self.api_key:
            logger.info(f"API key for {self.provider} is present")
            # Log the first few characters of the key for debugging (safely)
            if len(self.api_key) > 8:
                logger.debug(f"API key starts with: {self.api_key[:4]}...{self.api_key[-4:]}")
        else:
            logger.error(f"API key for {self.provider} is missing")
            
        self.endpoint = config["endpoint"]
        self.model = config["model"]
        self.max_tokens = config.get("max_tokens", 1500)
        
        if not self.api_key:
            raise ValueError(f"API key for {self.provider} not found in config or environment variables")

    def generate_response(self, prompt: str) -> str:
        """
        Generate a response from the configured AI model.
        
        Args:
            prompt: The prompt to send to the AI model
            
        Returns:
            The generated response text
            
        Raises:
            ValueError: If the provider is not supported
            RuntimeError: If the API call fails
        """
        if self.provider == "openai":
            return self._call_openai(prompt)
        elif self.provider == "anthropic":
            return self._call_anthropic(prompt)
        elif self.provider == "google":
            return self._call_google(prompt)
        elif self.provider == "mistral":
            return self._call_mistral(prompt)
        elif self.provider == "ollama":
            return self._call_ollama(prompt)
        elif self.provider == "huggingface":
            return self._call_huggingface(prompt)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Check if using new or old API format
        if "completions" in self.endpoint:
            # Legacy completions API
            payload = {
                "model": self.model,
                "prompt": prompt,
                "max_tokens": self.max_tokens,
                "temperature": 0.7,
            }
            response = requests.post(self.endpoint, json=payload, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"OpenAI API error: {response.text}")
                
            return response.json()["choices"][0]["text"]
        else:
            # Chat completions API
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": self.max_tokens,
                "temperature": 0.7,
            }
            response = requests.post(self.endpoint, json=payload, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"OpenAI API error: {response.text}")
                
            return response.json()["choices"][0]["message"]["content"]

    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        # Get the API key from environment variable directly to ensure it's correct
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            api_key = self.api_key
        else:
            # Clean the API key from environment variable
            api_key = api_key.strip().replace('\n', '').replace('\r', '')
            
        logger = logging.getLogger("ai-pr-reviewer")
        logger.debug(f"Using API key from {'environment variable' if api_key != self.api_key else 'config'}")
        
        # Verify the API key is valid
        if not api_key or len(api_key) < 8:
            logger.error("API key is missing or invalid")
            raise RuntimeError("Anthropic API key is missing or invalid")
            
        # Log the first few characters of the key for debugging (safely)
        logger.debug(f"API key starts with: {api_key[:4]}...{api_key[-4:]}")
        
        # Use the correct authentication header for Anthropic API
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        # Try with the newer Anthropic API format
        try:
            # Updated payload format for Anthropic Claude API
            payload = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.5  # Lower temperature for more consistent formatting
            }
            
            response = requests.post(self.endpoint, json=payload, headers=headers)
            
            # If we get a 404 error, try with the latest model
            if response.status_code == 404:
                logger.warning(f"Model {self.model} not found, trying with claude-3-opus-latest")
                payload["model"] = "claude-3-opus-latest"
                response = requests.post(self.endpoint, json=payload, headers=headers)
            
            if response.status_code != 200:
                # Try with updated headers for newer API
                headers = {
                    "anthropic-api-key": api_key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01"
                }
                response = requests.post(self.endpoint, json=payload, headers=headers)
                
                if response.status_code != 200:
                    # Try with Authorization header
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    }
                    response = requests.post(self.endpoint, json=payload, headers=headers)
                    
                    if response.status_code != 200:
                        # Log the error for debugging
                        logger.error(f"Anthropic API error: {response.status_code} - {response.text}")
                        raise RuntimeError(f"Anthropic API error: {response.status_code} - {response.text}")
        except Exception as e:
            raise RuntimeError(f"Anthropic API error: {str(e)}")
        
        # Handle Claude 3 response format
        response_json = response.json()
        
        # Use proper logging instead of print
        logger = logging.getLogger("ai-pr-reviewer")
        logger.debug(f"Anthropic response keys: {list(response_json.keys())}")
        
        # Claude 3 format (messages API)
        if "content" in response_json:
            # Extract all text content from the response
            if isinstance(response_json["content"], list):
                text_parts = []
                for item in response_json["content"]:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and "text" in item:
                            text_parts.append(item["text"])
                        elif "text" in item:
                            text_parts.append(item["text"])
                        elif "value" in item:
                            text_parts.append(item["value"])
                
                if text_parts:
                    result = "\n".join(text_parts)
                    logger.debug(f"Extracted text from content list: {result[:100]}...")
                    return result
        
        # Try direct content access
        if "content" in response_json and len(response_json["content"]) > 0:
            content_item = response_json["content"][0]
            if isinstance(content_item, dict):
                if "text" in content_item:
                    result = content_item["text"]
                    logger.debug(f"Extracted text from content[0].text: {result[:100]}...")
                    return result
                elif "value" in content_item:
                    result = content_item["value"]
                    logger.debug(f"Extracted text from content[0].value: {result[:100]}...")
                    return result
        
        # Legacy format
        if "completion" in response_json:
            result = response_json["completion"]
            logger.debug(f"Extracted text from completion: {result[:100]}...")
            return result
        
        # Try to extract from the 'message' field if it exists
        if "message" in response_json:
            message = response_json["message"]
            if isinstance(message, dict) and "content" in message:
                if isinstance(message["content"], list):
                    text_parts = []
                    for item in message["content"]:
                        if isinstance(item, dict) and "text" in item:
                            text_parts.append(item["text"])
                    if text_parts:
                        result = "\n".join(text_parts)
                        logger.debug(f"Extracted text from message.content: {result[:100]}...")
                        return result
                elif isinstance(message["content"], str):
                    result = message["content"]
                    logger.debug(f"Extracted text from message.content string: {result[:100]}...")
                    return result
        
        # Last resort: try to extract any text we can find
        try:
            # Log the full response for debugging
            logger.error(f"Could not extract text using standard methods. Full response: {response_json}")
            
            # Try to convert to string as a last resort
            result = str(response_json)
            logger.debug(f"Converted full response to string: {result[:100]}...")
            return result
        except Exception as e:
            logger.error(f"Error converting response to string: {str(e)}")
            raise RuntimeError(f"Unexpected Anthropic API response format: {response_json}")

    def _call_google(self, prompt: str) -> str:
        """Call Google Gemini API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
                "temperature": 0.7
            }
        }
        
        response = requests.post(self.endpoint, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Google Gemini API error: {response.text}")
            
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _call_mistral(self, prompt: str) -> str:
        """Call Mistral AI API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0.7
        }
        
        response = requests.post(self.endpoint, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Mistral API error: {response.text}")
            
        return response.json()["choices"][0]["message"]["content"]

    def _call_ollama(self, prompt: str) -> str:
        """Call local Ollama API."""
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": self.max_tokens
            }
        }
        
        response = requests.post(self.endpoint, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Ollama API error: {response.text}")
            
        return response.json()["response"]

    def _call_huggingface(self, prompt: str) -> str:
        """Call Hugging Face Inference API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": self.max_tokens,
                "temperature": 0.7
            }
        }
        
        response = requests.post(self.endpoint, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Hugging Face API error: {response.text}")
            
        # Handle different response formats from Hugging Face
        response_json = response.json()
        if isinstance(response_json, list) and len(response_json) > 0:
            return response_json[0]["generated_text"].replace(prompt, "")
        elif isinstance(response_json, dict) and "generated_text" in response_json:
            return response_json["generated_text"].replace(prompt, "")
        else:
            return str(response_json)