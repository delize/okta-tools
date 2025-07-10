# Python Script Summary

## What This Does
- **Generates Terraform Files:**  
  - Creates Terraform configuration files for Okta sign-on policies and their rules.
- **Environment Modes:**  
  - Supports both single environment mode and dual environment mode (test/preview and production).
- **Data Retrieval:**  
  - Fetches policy data from the Okta API or, in test mode, from local JSON files.
- **Terraform Formatting:**  
  - Optionally formats the generated Terraform files using `terraform fmt`.

## APIs It Calls
- **Okta API for Policies:**  
  - **Endpoint:** `/api/v1/policies?type=ACCESS_POLICY`  
  - **Method:** GET  
  - **Headers:**  
    - `Authorization: SSWS {api_token}`  
    - `Accept: application/json`
- **Okta API for Policy Rules:**  
  - **Endpoint:** `/api/v1/policies/{policy_id}/rules`  
  - **Method:** GET  
  - **Headers:**  
    - `Authorization: SSWS {api_token}`  
    - `Accept: application/json`
- **Terraform Command:**  
  - Runs `terraform fmt` via a subprocess call on generated directories.

## What the Arguments Are For
- **Mode Selection:**  
  - `--dual`: Activates dual environment mode for generating files for both preview and production.
- **Single Environment Arguments:**  
  - `--api-token`: API token for Okta (used only in single environment mode).  
  - `--full-url`: Full Okta API base URL.  
  - `--subdomain`: Okta subdomain used to build the API URL when `--full-url` is not provided.  
  - `--domain-flag`: Specifies the Okta domain suffix (e.g., `default`, `emea`, `preview`, `gov`, `mil`).
- **Dual Environment Arguments:**  
  - **Preview Environment:**  
    - `--preview-full-url`: Full URL for the preview Okta API.  
    - `--preview-subdomain`: Okta subdomain for the preview environment.  
    - `--preview-domain-flag`: Domain flag for the preview environment (default is `preview`).  
    - `--preview-api-token`: API token for the preview environment (or via `OKTA_PREVIEW_API_TOKEN`).
  - **Production Environment:**  
    - `--prod-full-url`: Full URL for the production Okta API.  
    - `--prod-subdomain`: Okta subdomain for the production environment.  
    - `--prod-domain-flag`: Domain flag for the production environment (default is `default`).  
    - `--prod-api-token`: API token for the production environment (or via `OKTA_PROD_API_TOKEN`).
- **Additional Options:**  
  - `--test`: Uses local JSON files for policies and rules instead of live API calls.
  - `--fmt`: Executes `terraform fmt` on the generated files to format them.

## What the Terraform Generated File Will Look Like
- **Policy Resource Block:**  
  - Named based on a sanitized version of the policy name, with an optional environment suffix.
  - Contains attributes like `name` and `description`, with conditional resource creation using the `count` parameter when an environment is specified.
- **Import Block for the Policy:**  
  - Specifies the resource to import, including its ID.
- **Rule Resource Blocks:**  
  - Each rule gets its own resource block with a unique name combining the policy and rule names, including attributes such as:
    - `policy_id` linking back to the parent policy.
    - Various rule-specific settings (e.g., `inactivity_period`, `status`, `access`, `factor_mode`).
    - Conditional attributes and lifecycle rules, especially for "catch-all" rules.
  - Each rule is followed by an import block that includes the composite ID (`policy_id/rule_id`).