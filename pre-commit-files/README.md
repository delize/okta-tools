# Pre-Commit Hooks for Terraform Repository

## Overview
This repository uses [pre-commit](https://pre-commit.com/) to enforce coding standards, validate Terraform configurations, and maintain best practices before commits.

## Installation
Ensure you have Python installed, then install `pre-commit` globally:

```bash
pip install pre-commit
```

Alternatively, install via:
- **MacOS (Homebrew)**: `brew install pre-commit`
- **Linux (APT-based distros)**: `sudo apt install pre-commit`
- **Windows (Scoop)**: `scoop install pre-commit`

## Setup
Run the following command inside the repository to install the Git hook:

```bash
pre-commit install
```

This ensures that hooks run automatically before each commit.

## Configuration
The `.pre-commit-config.yaml` file defines hooks for Terraform validation and best practices. Example:

```yaml
repos:
  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.77.0
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
      - id: terraform_tflint
      - id: terraform_docs
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
  - repo: local
    hooks:
      - id: api-key-check
        name: API Key Detector
        entry: bash .git-hooks/pre-commit-api-key.sh
        language: system
        pass_filenames: true
        types: [text]
      - id: check-okta-group-rule-quotes
        name: Check for Unescaped Quotes in Okta Group Rules
        entry: bash .git-hooks/check_okta_group_rule_quotes.sh
        language: system
        types: [text]
        files: \.tf$
```

## API Key Detection Hook
This repository includes a **pre-commit hook to detect API keys** in staged files before committing. The hook scans for commonly used API key patterns (e.g., AWS, Google, Stripe, GitHub, Slack, Terraform) and prevents committing sensitive credentials.

### How It Works
- Runs before each commit.
- Scans all staged text files for API key patterns.
- If an API key is found, the commit is rejected, and a warning is displayed.
- Supports detection for AWS, Google, Stripe, GitHub, Slack, Facebook, Mailchimp, Okta, Terraform, and more.

### Running API Key Detection Manually
To check all files manually:

```bash
pre-commit run api-key-check --all-files
```

## Okta Group Rule Quotes Check
This repository includes a **pre-commit hook to check for unescaped double quotes in Okta Group Rules** within Terraform `.tf` files. This ensures that `expression_value` attributes in `okta_group_rule` resources do not contain unescaped quotes, which can cause deployment errors.

### How It Works
- Runs before each commit.
- Scans all staged `.tf` files for unescaped double quotes within `expression_value`.
- If an issue is found, the commit is rejected with an error message.

### Running Okta Group Rule Quotes Check Manually
To check Terraform files manually:

```bash
pre-commit run check-okta-group-rule-quotes --all-files
```

## Running Hooks Manually
To run pre-commit hooks on all files:

```bash
pre-commit run --all-files
```

To run only Terraform-specific hooks:

```bash
pre-commit run terraform_fmt --all-files
```

## Updating Hooks
To update pre-commit hooks to their latest versions:

```bash
pre-commit autoupdate
```

## Skipping Pre-Commit Checks
If needed, bypass hooks for a commit:

```bash
git commit --no-verify -m "Bypass pre-commit checks"
```

## Uninstalling Pre-Commit
To remove pre-commit from the repository:

```bash
pre-commit uninstall
```

## Troubleshooting
- If a hook fails, review the error message and ensure dependencies are installed.
- Check `.git/hooks/pre-commit` for script execution issues.

## References
- [Pre-Commit Documentation](https://pre-commit.com/)
- [Terraform Pre-Commit Hooks](https://github.com/antonbabenko/pre-commit-terraform)

