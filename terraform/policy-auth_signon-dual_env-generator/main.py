#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import requests
import subprocess
import os

def run_terraform_fmt(generated_dirs):
    for folder in generated_dirs:
        if os.path.isdir(folder):
            try:
                subprocess.run(["terraform", "fmt", folder], check=True)
                print(f"Formatted files in {folder}")
            except subprocess.CalledProcessError as e:
                print(f"Error running terraform fmt in {folder}: {e}")

def sanitize_filename(name):
    # Remove any characters that are not alphanumeric, underscore, or dash.
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return sanitized.lower()

def get_okta_domain(subdomain, domain_flag):
    """
    Build the Okta domain URL using a subdomain and domain_flag.
    domain_flag can be 'default', 'emea', 'preview', 'gov', or 'mil'.
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
    policy_name = sanitize_filename(policy.get("name", "unnamed_policy"))
    tf_lines = []

    # Generate the policy resource block.
    tf_lines.append(f'resource "okta_app_signon_policy" "policy_{policy_name}_{env_name}" {{')
    if env_name:
        tf_lines.append(f'  count = var.CONFIG == "{env_name}" ? 1 : 0')
    tf_lines.append(f'  name = "{policy.get("name", "")}"')
    desc = policy.get("description", "").replace("\n", " ").strip()
    if desc:
        tf_lines.append(f'  description = {json.dumps(desc)}')
    else:
        tf_lines.append('  description = ""')
    tf_lines.append("}\n")

    # Generate the import block for the policy.
    tf_lines.append("import {")
    if env_name:
        tf_lines.append(f'  for_each = var.CONFIG == "{env_name}" ? toset(["{env_name}"]) : []')
    tf_lines.append(f'  to = okta_app_signon_policy.policy_{policy_name}_{env_name}[0]')
    tf_lines.append(f'  id = "{policy.get("id")}"')
    tf_lines.append("}\n")

    # Generate resource blocks for each rule.
    for rule in rules:
        rule_name_raw = rule.get("name", "unnamed_rule")
        rule_name = sanitize_filename(rule_name_raw)
        # Create a unique name by combining the policy and rule names.
        unique_rule_name = f"{policy_name}_{rule_name}_{env_name}"
        rule_id = rule.get("id", "")
        tf_lines.append(f'resource "okta_app_signon_policy_rule" "rule_{unique_rule_name}" {{')
        if env_name:
            tf_lines.append(f'  count = var.CONFIG == "{env_name}" ? 1 : 0')
        tf_lines.append(f'  policy_id = okta_app_signon_policy.policy_{policy_name}_{env_name}[0].id')
        tf_lines.append(f'  depends_on = [okta_app_signon_policy.policy_{policy_name}_{env_name}[0]]')
        tf_lines.append(f'  name      = "{rule_name_raw}"')

        # Extract data from actions.
        actions = rule.get("actions", {}).get("appSignOn", {})
        verification = actions.get("verificationMethod", {})

        # Inactivity period: if the API returns a value, use it;
        # otherwise, output null (without quotes)
        inactivity_period = verification.get("inactivityPeriod")
        if inactivity_period:
            if not (rule.get("priority") == 99 or rule.get("name", "").strip().lower() == "catch-all rule"):
                tf_lines.append(f'  inactivity_period = "{inactivity_period}"')
        else:
            if not (rule.get("priority") == 99 or rule.get("name", "").strip().lower() == "catch-all rule"):
                tf_lines.append('  inactivity_period = ""')
                tf_lines.append("  lifecycle {")
                tf_lines.append('    ignore_changes = [inactivity_period]')
                tf_lines.append("  }")
            
        if rule.get("status"):
            tf_lines.append(f'  status = "{rule["status"]}"')

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
        # if "network" in conditions and "connection" in conditions["network"]:
        #     tf_lines.append(f'  network_connection = "{conditions["network"]["connection"]}"')
        if "network" in conditions:
            network = conditions["network"]
            if "connection" in network:
                tf_lines.append(f'  network_connection = "{network["connection"]}"')
            if "exclude" in network:
                tf_lines.append(f'  network_excludes = {json.dumps(network["exclude"])}')
            if "include" in network:
                tf_lines.append(f'  network_includes = {json.dumps(network["include"])}')

        if "device" in conditions:
            if "registered" in conditions["device"]:
                tf_lines.append(f'  device_is_registered = {str(conditions["device"]["registered"]).lower()}')
            if "managed" in conditions["device"]:
                tf_lines.append(f'  device_is_managed = {str(conditions["device"]["managed"]).lower()}')
        if "riskScore" in conditions and "level" in conditions["riskScore"]:
            tf_lines.append(f'  risk_score = "{conditions["riskScore"]["level"]}"')
        if "people" in conditions:
            people = conditions["people"]
            if "groups" in people:
                groups = people["groups"]
                if "include" in groups:
                    groups_included = groups["include"]
                    if groups_included:
                        tf_lines.append(f'  groups_included = {json.dumps(groups_included)}')
                if "exclude" in groups:
                    groups_excluded = groups["exclude"]
                    if groups_excluded:
                        tf_lines.append(f'  groups_excluded = {json.dumps(groups_excluded)}')
            if "users" in people:
                users = people["users"]
                if "include" in users:
                    users_included = users["include"]
                    if users_included:
                        tf_lines.append(f'  users_included = {json.dumps(users_included)}')
                if "exclude" in users:
                    users_excluded = users["exclude"]
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
        
        # Process platform includes (as above)
        # Process platform includes
        platform_data = conditions.get("platform", {})
        platform_includes = platform_data.get("include", [])
        if platform_includes:
            for plat in platform_includes:
                tf_lines.append("  platform_include {")
                # Get the OS type from the nested "os" dictionary.
                if "os" in plat and "type" in plat["os"]:
                    tf_lines.append(f'    os_type = "{plat["os"]["type"]}"')
                # The platform's own type (e.g. DESKTOP, MOBILE)
                if "type" in plat:
                    tf_lines.append(f'    type = "{plat["type"]}"')
                # If there's an os_expression key, handle it (if applicable)
                if "os_expression" in plat:
                    tf_lines.append(f'    os_expression = "{plat["os_expression"]}"')
                tf_lines.append("  }")
        if rule.get("custom_expression"):
            tf_lines.append(f'  custom_expression = "{rule["custom_expression"]}"')
        
        if "device_assurances_included" in rule:
            tf_lines.append(f'  device_assurances_included = {json.dumps(rule["device_assurances_included"])}')
     

        

        # For catch-all rules, add a lifecycle block to ignore immutable changes.
        if rule.get("priority") == 99 or rule.get("name", "").strip().lower() == "catch-all rule":
            tf_lines.append("  lifecycle {")
            tf_lines.append("    ignore_changes = [")
            tf_lines.append('      network_connection,')
            tf_lines.append('      network_excludes,')
            tf_lines.append('      network_includes,')
            tf_lines.append('      platform_include,')
            tf_lines.append('      custom_expression,')
            tf_lines.append('      inactivity_period,')
            tf_lines.append('      device_is_registered,')
            tf_lines.append('      device_is_managed,')
            tf_lines.append('      users_excluded,')
            tf_lines.append('      users_included,')
            tf_lines.append('      groups_excluded,')
            tf_lines.append('      groups_included,')
            tf_lines.append('      user_types_excluded,')
            tf_lines.append('      user_types_included,')
            tf_lines.append('      re_authentication_frequency,')
            tf_lines.append('      factor_mode,')
            tf_lines.append('      constraints,')
            tf_lines.append("    ]")
            tf_lines.append("  }")

        tf_lines.append("}\n")

        # Generate the import block for the rule.
        tf_lines.append("import {")
        if env_name:
            tf_lines.append(f'  for_each = var.CONFIG == "{env_name}" ? toset(["{env_name}"]) : []')
        tf_lines.append(f'  to = okta_app_signon_policy_rule.rule_{unique_rule_name}[0]')
        tf_lines.append(f'  id = "{policy.get("id")}/{rule.get("id")}"')
        tf_lines.append("}\n")

    return "\n".join(tf_lines)

def main():
    parser = argparse.ArgumentParser(
        description="Generate Terraform files for Okta Authentication Policies and Rules for single or dual environments."
    )
    parser.add_argument("--dual", action="store_true",
                        help="Generate files for both preview (test) and production (prod) environments.")
    parser.add_argument("--api-token",
                        help="API token for single environment mode. Ignored in dual mode.")
    # Single environment arguments.
    parser.add_argument("--full-url",
                        help="Full base URL for the Okta API (single environment).")
    parser.add_argument("--subdomain",
                        help="Your Okta subdomain for single environment (ignored if --full-url is provided).")
    parser.add_argument("--domain-flag", choices=["default", "emea", "preview", "gov", "mil"], default="default",
                        help="Base domain flag for single environment (default: okta.com).")
    # Dual environment arguments.
    parser.add_argument("--preview-full-url",
                        help="Full base URL for the preview Okta API (dual mode).")
    parser.add_argument("--preview-subdomain",
                        help="Preview Okta subdomain (dual mode).")
    parser.add_argument("--preview-domain-flag", default="preview",
                        help="Domain flag for preview environment (dual mode, default: preview).")
    parser.add_argument("--preview-api-token",
                        help="API token for the preview environment. If not provided, will look for OKTA_PREVIEW_API_TOKEN in the environment.")
    parser.add_argument("--prod-full-url",
                        help="Full base URL for the production Okta API (dual mode).")
    parser.add_argument("--prod-subdomain",
                        help="Production Okta subdomain (dual mode).")
    parser.add_argument("--prod-domain-flag", default="default",
                        help="Domain flag for production environment (dual mode, default: default).")
    parser.add_argument("--prod-api-token",
                        help="API token for the production environment. If not provided, will look for OKTA_PROD_API_TOKEN in the environment.")
    parser.add_argument("--test", action="store_true",
                        help="Run in test mode using local JSON files for policies and rules.")
    parser.add_argument("--fmt",  action="store_true",
                        help="Run 'terraform fmt' on the generated Terraform files after generation.")
    args = parser.parse_args()

    environments = []
    if args.dual:
        # Process preview environment.
        if args.preview_full_url:
            preview_url = args.preview_full_url.rstrip('/')
        elif args.preview_subdomain:
            preview_url = get_okta_domain(args.preview_subdomain, args.preview_domain_flag)
        else:
            print("Error: For dual environment, preview environment parameters are required.")
            sys.exit(1)
        preview_token = args.preview_api_token or os.getenv("OKTA_PREVIEW_API_TOKEN")
        if not preview_token:
            print("Error: For dual environment, preview API token must be provided via --preview-api-token or OKTA_PREVIEW_API_TOKEN.")
            sys.exit(1)
        environments.append({"name": "test", "base_url": preview_url, "api_token": preview_token})

        # Process production environment.
        if args.prod_full_url:
            prod_url = args.prod_full_url.rstrip('/')
        elif args.prod_subdomain:
            prod_url = get_okta_domain(args.prod_subdomain, args.prod_domain_flag)
        else:
            print("Error: For dual environment, production environment parameters are required.")
            sys.exit(1)
        prod_token = args.prod_api_token or os.getenv("OKTA_PROD_API_TOKEN")
        if not prod_token:
            print("Error: For dual environment, production API token must be provided via --prod-api-token or OKTA_PROD_API_TOKEN.")
            sys.exit(1)
        environments.append({"name": "prod", "base_url": prod_url, "api_token": prod_token})
    else:
        # Single environment mode.
        if args.full_url:
            base_url = args.full_url.rstrip('/')
        elif args.subdomain:
            base_url = get_okta_domain(args.subdomain, args.domain_flag)
        else:
            print("Error: For single environment mode, provide either --full-url or --subdomain.")
            sys.exit(1)
        single_token = args.api_token or os.getenv("OKTA_API_TOKEN")
        if not single_token:
            print("Error: API token must be provided via --api-token or OKTA_API_TOKEN for single environment mode.")
            sys.exit(1)
        environments.append({"name": None, "base_url": base_url, "api_token": single_token})

    for env in environments:
        env_suffix = f"_{env['name']}" if env["name"] else ""
        print(f"Using Okta domain: {env['base_url']} for environment: {env['name'] if env['name'] else 'single'}")
        try:
            policies = get_policies(env["base_url"], env["api_token"], test=args.test)
        except Exception as e:
            print(f"Error retrieving policies from {env['base_url']}: {e}")
            continue

        output_dir = env["name"] if env["name"] else "."
        if env["name"] and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        for policy in policies:
            policy_id = policy.get("id")
            if not policy_id:
                continue
            try:
                rules = get_policy_rules(env["base_url"], policy_id, env["api_token"], test=args.test)
            except Exception as e:
                print(f"Error retrieving rules for policy {policy.get('name')}: {e}")
                continue
            tf_content = generate_tf(policy, rules, env_name=env["name"])
            filename = f"zz_legacy_policy-{sanitize_filename(policy.get('name','unnamed_policy'))}{env_suffix}.tf"
            filepath = os.path.join(output_dir, filename) if env["name"] else filename
            with open(filepath, 'w') as f:
                f.write(tf_content)
            print(f"Generated Terraform file: {filepath}")

    # After generating files for each environment...
    # Build a list of output directories (only for environments with a name)
    generated_dirs = [env["name"] for env in environments if env["name"]]
    # If running in single-environment mode, you might want to use the current directory:
    if not generated_dirs:
        generated_dirs = ["."]
        
    if args.fmt:
        run_terraform_fmt(generated_dirs)

if __name__ == "__main__":
    main()