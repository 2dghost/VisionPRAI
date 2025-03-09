# Setting Up GitHub Secrets for AI PR Review

To use the AI PR review workflow, you need to set up secrets in your GitHub repository. These secrets will be used to authenticate with GitHub and the AI providers.

## Required Secrets

1. **GH_TOKEN**: GitHub token with permission to read repositories and write PR comments

2. **AI Provider API Key**: At least one of the following, depending on which provider you choose:
   - `OPENAI_API_KEY`: For OpenAI models (GPT-3.5, GPT-4)
   - `ANTHROPIC_API_KEY`: For Anthropic Claude models
   - `GOOGLE_API_KEY`: For Google Gemini models
   - `MISTRAL_API_KEY`: For Mistral AI models
   - `HUGGINGFACE_API_KEY`: For Hugging Face Inference API

## Step-by-Step Guide

### Creating a GitHub Token

1. Go to your GitHub account settings
2. Select "Developer settings" > "Personal access tokens" > "Fine-grained tokens" (or "Classic tokens")
3. Click "Generate new token"
4. Give it a descriptive name (e.g., "AI PR Review")
5. Set appropriate expiration
6. Select the repositories you want to use the token with
7. Add the following permissions:
   - Repository: Read access to metadata, code, and pull requests
   - Pull requests: Read and Write access
8. Generate token and copy it

### Obtaining AI Provider API Keys

Choose one of the following based on your preferred AI provider:

#### OpenAI API Key
1. Go to [OpenAI API platform](https://platform.openai.com/)
2. Create or log in to your account
3. Navigate to API Keys section
4. Create a new API key and copy it

#### Anthropic API Key
1. Visit [Anthropic Console](https://console.anthropic.com/)
2. Create or log in to your account
3. Go to the API Keys section
4. Generate a new API key and copy it

#### Google API Key (for Gemini)
1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create or log in to your account
3. Generate a new API key and copy it

### Adding Secrets to Your Repository

1. Go to your GitHub repository
2. Click on "Settings" > "Secrets and variables" > "Actions"
3. Click "New repository secret"
4. Add each secret with its appropriate name (e.g., `GH_TOKEN`, `OPENAI_API_KEY`)
5. Paste the corresponding token/key value
6. Click "Add secret"

## Verifying Setup

Once you've added the secrets:

1. Make sure the PR review workflow file (`.github/workflows/pr-review.yml`) references the correct secret names
2. In `config.yaml`, ensure the `provider` is set to match the API key you've provided
3. Create a test PR to verify the workflow runs correctly

## Security Considerations

- Regularly rotate your API keys for better security
- Set appropriate token expirations
- Use the minimum required permissions for your GitHub token
- Never commit API keys or tokens to your repository