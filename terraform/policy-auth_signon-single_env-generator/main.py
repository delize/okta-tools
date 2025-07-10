#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys

import requests

def sanitize_filename(name):
    # Remove any characters that are not alphanumeric, underscore, or dash.
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return sanitized.lower()

def get_okta_domain(subdomain, domain_flag):
    """
    Build the Okta domain URL using a subdomain and domain_flag:
      - domain_flag can be 'default', 'emea', 'preview', 'gov', or 'mil'.
    """
    domain_map = {
        "default": "okta.com",
        "emea": "okta-emea.com",
        "preview": "oktapreview.com",
        "gov": "okta-gov.com",
        "mil": "okta.mil"
    }
    domain = domain_map.get(domain_flag, "okta.com")
    return f"https://{subdomain}.{domain}"

def get_policies(base_url, api_token, test=False):
    """
    Retrieves policies from the Okta API or a local file if testing.
    """
    if test:
        with open('policies.json', 'r') as f:
            policies = json.load(f)
    else:
        url = f"{base_url}/api/v1/policies?type=ACCESS_POLICY"
        headers = {"Authorization": f"SSWS {api_token}", "Accept": "application/json"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        policies = response.json()
    return policies

def get_policy_rules(base_url, policy_id, api_token, test=False):
    """
    Retrieves rules for a given policy from the Okta API or a local file if testing.
    """
    if test:
        with open('rules-response.json', 'r') as f:
            rules = json.load(f)
    else:
        url = f"{base_url}/api/v1/policies/{policy_id}/rules"
        headers = {"Authorization": f"SSWS {api_token}", "Accept": "application/json"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        rules = response.json()
    return rules

def generate_tf(policy, rules, env_name=None):
    """
    Generates Terraform configuration for a given policy and its rules,
    including resource definitions and HCL import blocks.
    
    If env_name is provided (e.g. "prod" or "test"), then:
      - Each resource block will include:
            count = var.CONFIG == "{env_name}" ? 1 : 0
      - Each import block will include:
            for_each = var.CONFIG == "{env_name}" ? toset(["{env_name}"]) : []
    """
    # Sanitize the policy name
    policy_name = sanitize_filename(policy.get("name", "unnamed_policy"))
    tf_lines = []

    # Determine a unique policy name that includes the environment if provided.
    if env_name:
        unique_policy_name = f"{policy_name}_{env_name}"
    else:
        unique_policy_name = policy_name

    # Generate the policy resource block.
    tf_lines.append(f'resource "okta_app_signon_policy" "policy_{unique_policy_name}" {{')
    if env_name:
        tf_lines.append(f'  count = var.CONFIG == "{env_name}" ? 1 : 0')
    tf_lines.append(f'  name = "{policy.get("name", "")}"')
    if policy.get("description"):
        tf_lines.append(f'  description = {json.dumps(policy.get("description", "").replace("\n", " "))}')
    else:
        tf_lines.append('  description = null')
    tf_lines.append("}\n")

    # Generate the import block for the policy.
    tf_lines.append("import {")
    if env_name:
        tf_lines.append(f'  for_each = var.CONFIG == "{env_name}" ? toset(["{env_name}"]) : []')
    tf_lines.append(f'  to = okta_app_signon_policy.policy_{unique_policy_name}[0]')
    tf_lines.append(f'  id = "{policy.get("id")}"')
    tf_lines.append("}\n")

    # Generate resource blocks for each rule.
    for rule in rules:
        rule_name_raw = rule.get("name", "unnamed_rule")
        rule_name = sanitize_filename(rule_name_raw)
        # Create a unique name by combining the policy and rule names.
        if env_name:
            unique_rule_name = f"{policy_name}_{env_name}_{rule_name}"
        else:
            unique_rule_name = f"{policy_name}_{rule_name}"
        rule_id = rule.get("id", "")
        tf_lines.append(f'resource "okta_app_signon_policy_rule" "rule_{unique_rule_name}" {{')
        if env_name:
            tf_lines.append(f'  count = var.CONFIG == "{env_name}" ? 1 : 0')
        tf_lines.append(f'  policy_id = okta_app_signon_policy.policy_{policy_name}.id')
        tf_lines.append(f'  depends_on = [okta_app_signon_policy.policy_{policy_name}]')
        tf_lines.append(f'  name      = "{rule_name_raw}"')

        # Extract data from actions.
        actions = rule.get("actions", {}).get("appSignOn", {})
        verification = actions.get("verificationMethod", {})

        if "access" in actions:
            tf_lines.append(f'  access = "{actions["access"]}"')
        if "factorMode" in verification:
            tf_lines.append(f'  factor_mode = "{verification["factorMode"]}"')
        if "reauthenticateIn" in verification:
            tf_lines.append(f'  re_authentication_frequency = "{verification["reauthenticateIn"]}"')
        if "type" in verification:
            tf_lines.append(f'  type = "{verification["type"]}"')

        # Output constraints if available.
        constraints = verification.get("constraints")
        if constraints:
            tf_lines.append("  constraints = [")
            for c in constraints:
                constraint_str = json.dumps(c, separators=(',', ':'))
                tf_lines.append(f'    jsonencode({constraint_str}),')
            tf_lines.append("  ]")

        # Extract condition details safely.
        conditions = rule.get("conditions") or {}
        if "network" in conditions and "connection" in conditions["network"]:
            tf_lines.append(f'  network_connection = "{conditions["network"]["connection"]}"')
        if "device" in conditions:
            if "registered" in conditions["device"]:
                tf_lines.append(f'  device_is_registered = {str(conditions["device"]["registered"]).lower()}')
            if "managed" in conditions["device"]:
                tf_lines.append(f'  device_is_managed = {str(conditions["device"]["managed"]).lower()}')
        if "riskScore" in conditions and "level" in conditions["riskScore"]:
            tf_lines.append(f'  risk_score = "{conditions["riskScore"]["level"]}"')
        if "people" in conditions:
            people = conditions["people"]
            if "groups" in people and "include" in people["groups"]:
                groups_included = people["groups"]["include"]
                if groups_included:
                    tf_lines.append(f'  groups_included = {json.dumps(groups_included)}')
            if "users" in people and "exclude" in people["users"]:
                users_excluded = people["users"]["exclude"]
                if users_excluded:
                    tf_lines.append(f'  users_excluded = {json.dumps(users_excluded)}')
        if "userType" in conditions and isinstance(conditions["userType"], dict):
            if "include" in conditions["userType"]:
                user_types_included = conditions["userType"]["include"]
                if user_types_included:
                    tf_lines.append(f'  user_types_included = {json.dumps(user_types_included)}')
            if "exclude" in conditions["userType"]:
                user_types_excluded = conditions["userType"]["exclude"]
                if user_types_excluded:
                    tf_lines.append(f'  user_types_excluded = {json.dumps(user_types_excluded)}')
        if "priority" in rule:
            tf_lines.append(f'  priority = {rule["priority"]}')

        # For catch-all rules, add a lifecycle block to ignore immutable changes.
        if rule.get("priority") == 99 or rule.get("name", "").strip().lower() == "catch-all rule":
            tf_lines.append("  lifecycle {")
            tf_lines.append("    ignore_changes = [")
            tf_lines.append('      "network_connection",')
            tf_lines.append('      "network_excludes",')
            tf_lines.append('      "network_includes",')
            tf_lines.append('      "platform_include",')
            tf_lines.append('      "custom_expression",')
            tf_lines.append('      "device_is_registered",')
            tf_lines.append('      "device_is_managed",')
            tf_lines.append('      "users_excluded",')
            tf_lines.append('      "users_included",')
            tf_lines.append('      "groups_excluded",')
            tf_lines.append('      "groups_included",')
            tf_lines.append('      "user_types_excluded",')
            tf_lines.append('      "user_types_included",')
            tf_lines.append("    ]")
            tf_lines.append("  }")
            
        tf_lines.append("}\n")

        # Generate the import block for the rule.
        tf_lines.append("import {")
        if env_name:
            tf_lines.append(f'  for_each = var.CONFIG == "{env_name}" ? toset(["{env_name}"]) : []')
        tf_lines.append(f'  to = okta_app_signon_policy_rule.rule_{unique_rule_name}[0]')
        tf_lines.append(f'  id = "{rule_id}"')
        tf_lines.append("}\n")

    return "\n".join(tf_lines)

def write_tf_file(policy, tf_content):
    """
    Writes the generated Terraform configuration to a file.
    """
    policy_name = sanitize_filename(policy.get("name", "unnamed_policy"))
    filename = f"policy-auth_signon-{policy_name}.tf"
    with open(filename, 'w') as f:
        f.write(tf_content)
    print(f"Generated Terraform file: {filename}")

def main():
    parser = argparse.ArgumentParser(
        description="Generate Terraform files for Okta Authentication Policies and Rules."
    )
    parser.add_argument(
        "--api-token",
        help="Your Okta API token. If not provided, the script will try to read the OKTA_API_TOKEN environment variable."
    )
    parser.add_argument(
        "--subdomain",
        help="Your Okta subdomain (e.g., 'dev-12345'). Ignored if --full-url is provided."
    )
    parser.add_argument(
        "--domain-flag", choices=["default", "emea", "preview", "gov", "mil"], default="default",
        help="Specify the base domain flag (default: okta.com). Options: default, emea, preview, gov, mil. Ignored if --full-url is provided."
    )
    parser.add_argument(
        "--full-url",
        help="Full base URL for the Okta API. If provided, --subdomain and --domain-flag are ignored."
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Run in test mode using local JSON files for policies and rules."
    )
    args = parser.parse_args()

    # Use the API token provided via CLI or fallback to the environment variable.
    api_token = args.api_token or os.getenv("OKTA_API_TOKEN")
    if not api_token:
        print("Error: API token must be provided either via --api-token or the OKTA_API_TOKEN environment variable.")
        sys.exit(1)

    # Determine the base URL.
    if args.full_url:
        base_url = args.full_url.rstrip('/')
    elif args.subdomain:
        base_url = get_okta_domain(args.subdomain, args.domain_flag)
    else:
        print("Error: You must provide either --full-url or --subdomain.")
        sys.exit(1)
    
    print(f"Using Okta domain: {base_url}")

    try:
        policies = get_policies(base_url, api_token, test=args.test)
    except Exception as e:
        print(f"Error retrieving policies: {e}")
        sys.exit(1)

    for policy in policies:
        policy_id = policy.get("id")
        if not policy_id:
            continue

        try:
            rules = get_policy_rules(base_url, policy_id, api_token, test=args.test)
        except Exception as e:
            print(f"Error retrieving rules for policy {policy.get('name')}: {e}")
            continue

        tf_content = generate_tf(policy, rules)
        write_tf_file(policy, tf_content)

if __name__ == "__main__":
    main()