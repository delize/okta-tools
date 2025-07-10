#!/bin/bash

# Define the hook file path to exclude
HOOK_FILE=".git-hooks/pre-commit-api-key.sh"

# Define patterns for common API keys (AWS, Google, Stripe, GitHub, Slack, Facebook, Mailchimp, Okta, Terraform, etc.)
PATTERNS=(
    "AKIA[0-9A-Z]{16}"  # AWS Access Key ID
    "AIza[0-9A-Za-z-_]{35}"  # Google API Key
    "sk_live_[0-9a-zA-Z]{24}"  # Stripe Live Secret Key
    "ghp_[0-9a-zA-Z]{36}"  # GitHub Personal Access Token
    "xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24}"  # Slack Token
    "EAACEdEose0cBA[0-9A-Za-z]+"  # Facebook Access Token
    "[0-9a-f]{32}-us[0-9]{1,2}"  # Mailchimp API Key
    "AIza[0-9A-Za-z-_]{35}" #Firebase
    "mongodb(\+srv)?:\/\/[a-zA-Z0-9:_-]+@[a-zA-Z0-9.-]+" # MongoDB
    "postgres://[a-zA-Z0-9:_@%]+" #PostgresDB
    "([?&]sig=([a-zA-Z0-9%]+))" # Azure Shared Key
    "(eyJ[a-zA-Z0-9-_]+\.eyJ[a-zA-Z0-9-_]+\.?[a-zA-Z0-9-_]*)" #OAuth Tokens
    "glpat-[0-9a-zA-Z_-]{20}" #Gitlab
    "circleci_[0-9a-fA-F]{40}" #Circle CI TOkens
    "ddp_[a-zA-Z0-9]{40}" #Datadog
    "SK[0-9a-fA-F]{32}" #Twilio 
    "SG\.[a-zA-Z0-9-_]{22}\.[a-zA-Z0-9-_]{43}" #Sendgrid
    
    

    # Okta API Tokens (Allowing letters, numbers, underscores, and dashes)
    "00[A-Za-z0-9_-]{40}"  # Okta API Key (00xxxxxxxx-xxxxxxxxxxxxxxxxxxxxxx)

    # Terraform Cloud/Enterprise API Tokens
    "tfe\.[0-9a-zA-Z_-]{35}"  # Terraform Cloud API Key (tfe.xxxxxx-xxxxx)

    # Generic API Key formats (adjust based on your security needs)
    # "[A-Za-z0-9_-]{32}"  # Generic 32-character API keys
    # "[A-Za-z0-9_-]{40}"  # Generic 40-character API keys
    # "[A-Za-z0-9_-]{64}"  # Generic 64-character API keys
)

# Check staged files for API keys
FILES=$(git diff --cached --name-only --diff-filter=ACM)

for FILE in $FILES; do
    # Skip the hook file itself
    if [[ "$FILE" == "$HOOK_FILE" ]]; then
        continue
    fi

    # Skip binary files
    if file "$FILE" | grep -qE 'binary'; then
        continue
    fi

    for PATTERN in "${PATTERNS[@]}"; do
        if grep -E -q "$PATTERN" "$FILE"; then
            echo "❌ Commit rejected: API key detected in '$FILE'"
            echo "🔍 Found match for: $PATTERN"
            exit 1
        fi
    done
done

echo "✅ No API keys found. Proceeding with commit."
exit 0
