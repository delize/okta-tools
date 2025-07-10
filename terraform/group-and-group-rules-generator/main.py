#!/usr/bin/env python3

import os
import argparse
import requests
import csv
import json
import re
import pandas as pd

###############################################################################
# 1. Okta Domain Utilities
###############################################################################

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


###############################################################################
# 2. Fetching & Exporting Okta Groups
###############################################################################

def fetch_okta_groups(okta_domain, api_token):
    """
    Fetch all groups from the Okta API with pagination, 
    filtering only groups whose 'type' == 'OKTA_GROUP'.
    """
    url = f"{okta_domain}/api/v1/groups"
    headers = {"Authorization": f"SSWS {api_token}", "Accept": "application/json"}
    groups = []

    while url:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Error fetching groups: {response.status_code}, {response.text}")
            return []

        data = response.json()
        # Filter only OKTA_GROUP types
        groups.extend([g for g in data if g.get("type") == "OKTA_GROUP"])

        url = None
        if "link" in response.headers:
            links = response.headers["link"].split(", ")
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find("<") + 1 : link.find(">")]

    return groups

def process_and_export_groups(groups, output_csv="okta_groups_dynamic.csv"):
    """
    Process group data dynamically and export it to CSV with flexible headers.
    """
    # Collect all possible headers from group 'profile'
    headers = set(["id"])
    for group in groups:
        profile = group.get("profile", {})
        headers.update(profile.keys())

    headers = sorted(headers)  # Sort headers for consistency

    with open(output_csv, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()

        for group in groups:
            profile = group.get("profile", {})
            row = {"id": group["id"]}  # ID is mandatory

            for key in headers:
                if key == "id":
                    continue
                value = profile.get(key)
                if isinstance(value, bool):
                    # Keep bool as True/False
                    row[key] = value
                elif isinstance(value, str):
                    stripped = value.strip()
                    # Convert "true" / "false" strings to booleans
                    if stripped.lower() in ["true", "false"]:
                        row[key] = stripped.lower() == "true"
                    else:
                        row[key] = stripped if stripped else None
                else:
                    row[key] = None

            writer.writerow(row)

    print(f"CSV file '{output_csv}' (Okta Groups) has been created successfully.")


###############################################################################
# 3. Fetching & Exporting Okta Group Rules
###############################################################################

def fetch_okta_group_rules(okta_domain, api_token):
    """
    Fetch all group rules from the Okta API with pagination.
    Returns a list of rule objects (JSON).
    """
    url = f"{okta_domain}/api/v1/groups/rules"
    headers = {"Authorization": f"SSWS {api_token}", "Accept": "application/json"}
    rules = []

    while url:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Error fetching group rules: {response.status_code}, {response.text}")
            return []
        data = response.json()
        rules.extend(data)

        # Check if there's a 'next' link in the response headers
        url = None
        if "link" in response.headers:
            links = response.headers["link"].split(", ")
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find("<") + 1 : link.find(">")]

    return rules

def process_and_export_rules(rules, output_csv="okta_group_rules.csv"):
    """
    Process rule data dynamically and export it to CSV with flexible headers.
    """
    headers = {
        "id", "name", "status", "created", "lastUpdated", 
        "allGroupsValid", "excludedUsers", "excludedGroups"
    }

    # Dynamically discover new fields from 'conditions', 'actions', and '_embedded'
    for rule in rules:
        conditions = rule.get("conditions", {})
        actions = rule.get("actions", {}).get("assignUserToGroups", {})
        embedded = rule.get("_embedded", {}).get("groupIdToGroupNameMap", {})

        if "expression" in conditions:
            headers.update(conditions["expression"].keys())

        headers.update(actions.keys())
        headers.update(embedded.keys())

    headers = sorted(headers)

    with open(output_csv, "w", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers, quoting=csv.QUOTE_NONNUMERIC)
        writer.writeheader()

        for rule in rules:
            row = {
                "id": rule.get("id", None),
                "name": rule.get("name", "").replace('"', ''),
                "status": rule.get("status"),
                "created": rule.get("created", None),
                "lastUpdated": rule.get("lastUpdated", None),
                "allGroupsValid": rule.get("allGroupsValid", False)
            }

            conditions = rule.get("conditions", {})
            actions = rule.get("actions", {}).get("assignUserToGroups", {})
            embedded = rule.get("_embedded", {}).get("groupIdToGroupNameMap", {})

            row["excludedUsers"] = conditions.get("people", {}).get("users", {}).get("exclude", [])
            excluded_groups = conditions.get("people", {}).get("groups", {}).get("exclude", [])
            row["excludedGroups"] = ",".join(excluded_groups) if excluded_groups else None

            # Expression conditions
            if "expression" in conditions:
                for key in conditions["expression"]:
                    row[key] = conditions["expression"].get(key, "")

            # Actions
            for key in actions:
                val = actions.get(key, [])
                row[key] = ",".join(val) if val else None

            # Embedded group data
            for key, value in embedded.items():
                row[key] = value

            # Ensure final row has a value for each header
            row = {hdr: row.get(hdr, None) for hdr in headers}
            writer.writerow(row)

    print(f"CSV file '{output_csv}' (Okta Group Rules) has been created successfully.")


###############################################################################
# 4. Terraform Generation from CSV
###############################################################################

def load_csv(filename):
    """Load CSV file from the script's directory, handling missing files gracefully."""
    if not filename:
        print("Warning: No file path specified. Returning empty DataFrame.")
        return pd.DataFrame()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, filename)
    if not os.path.exists(file_path):
        print(f"Warning: File not found: {file_path}. Returning empty DataFrame.")
        return pd.DataFrame()

    return pd.read_csv(file_path)

def process_group_dynamic(value):
    """Ensure groupDynamic is properly formatted as a boolean or null."""
    if isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, str):
        val_str = value.strip().lower()
        if val_str in ["true", '"true"']:
            return "true"
        elif val_str in ["false", '"false"']:
            return "false"
        elif val_str in [
            "undefined", "none", "null", '"undefined"', 
            '"none"', '"null"', "this is an invalid field"
        ]:
            return "null"
    return "null"

def format_list(value):
    """Ensure a value is correctly formatted as a Terraform-compatible list."""
    if isinstance(value, list):
        return json.dumps(value)
    elif isinstance(value, str):
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            return value
        elif value:
            return json.dumps([value])
    return "[]"

def format_users_excluded(value):
    """Ensure users_excluded is always an empty array."""
    return "[]"

def clean_value(value, default=None):
    """Ensure proper handling of null values for Terraform."""
    if pd.isna(value) or value in ["Not Available", "None", "null"]:
        return None
    return value.replace('\n', ' ') if isinstance(value, str) else value

def escape_for_terraform_resources(value):
    """Escape double quotes for Terraform resource strings."""
    if value:
        return value.replace('"', '\\"')
    return value

def format_group_assignments(value):
    """Ensure group_assignments is a JSON list, splitting on commas if needed."""
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, str):
        val_str = value.strip()
        if "," in val_str:
            return json.dumps(val_str.split(","))
        elif val_str:
            return json.dumps([val_str])
    return "[]"

def generate_terraform_resources(group_data, group_rule_data):
    """Generate Terraform resource blocks for Okta groups & group rules."""
    terraform_config = []

    # Groups
    for env, groups in group_data.items():
        for _, group in groups.iterrows():
            group_name = escape_for_terraform_resources(clean_value(group.get("name")))
            group_id = clean_value(group.get("id"))
            group_description = clean_value(group.get("description"))
            adminNotes = clean_value(group.get("adminNotes"))
            group_dynamic = process_group_dynamic(group.get("groupDynamic"))
            status = rule.get("status", [])
            group_owner = clean_value(group.get("groupOwner"))

            terraform_config.append(f'resource "okta_group" "group_{env}_{group_id}" {{')
            terraform_config.append(f'  count = var.CONFIG == "{env}" ? 1 : 0')
            terraform_config.append(f'  name        = "{group_name}"')
            terraform_config.append(f'  description = {json.dumps(group_description) if group_description else "null"}')
            terraform_config.append('  custom_profile_attributes = jsonencode({')
            terraform_config.append(f'    "adminNotes" = {json.dumps(adminNotes) if adminNotes else "null"},')
            terraform_config.append(f'    "groupDynamic" = {group_dynamic},')
            terraform_config.append(f'    "groupOwner" = {json.dumps(group_owner) if group_owner else "null"}')
            terraform_config.append('  })')
            terraform_config.append('  lifecycle { ignore_changes = [skip_users] }')
            terraform_config.append('}')
            terraform_config.append('')

    # Group Rules
    for env, rules in group_rule_data.items():
        for _, rule in rules.iterrows():
            rule_id = clean_value(rule.get("id"))
            rule_name = escape_for_terraform_resources(clean_value(rule.get("name")))
            group_assignments = format_group_assignments(clean_value(rule.get("groupIds", [])))
            users_excluded = format_users_excluded(clean_value(rule.get("excludedUsers", [])))
            expression_type = clean_value(rule.get("type", "urn:okta:expression:1.0"))
            expression_value = escape_for_terraform_resources(clean_value(rule.get("value")))

            terraform_config.append(f'resource "okta_group_rule" "rule_{env}_{rule_id}" {{')
            terraform_config.append(f'  count = var.CONFIG == "{env}" ? 1 : 0')
            terraform_config.append(f'  name   = "{rule_name}"')
            terraform_config.append(f'  status   = "{status}"')
            terraform_config.append(f'  group_assignments = {group_assignments}')
            terraform_config.append(f'  expression_type  = "{expression_type}"')
            terraform_config.append(f'  expression_value = "{expression_value}"')
            terraform_config.append(f'  users_excluded   = {users_excluded}')
            terraform_config.append('}')
            terraform_config.append('')

    return "\n".join(terraform_config)

def generate_terraform_imports(group_data, group_rule_data):
    """Generate import blocks for Okta groups & rules."""
    import_blocks = []

    # Groups
    for env, groups in group_data.items():
        for _, group in groups.iterrows():
            group_id = clean_value(group.get("id"))
            import_blocks.append('import {')
            import_blocks.append(f'  for_each = var.CONFIG == "{env}" ? toset(["{env}"]) : []')
            import_blocks.append(f'  to = okta_group.group_{env}_{group_id}[0]')
            import_blocks.append(f'  id = "{group_id}"')
            import_blocks.append('}')
            import_blocks.append('')

    # Rules
    for env, rules in group_rule_data.items():
        for _, rule in rules.iterrows():
            rule_id = clean_value(rule.get("id"))
            import_blocks.append('import {')
            import_blocks.append(f'  for_each = var.CONFIG == "{env}" ? toset(["{env}"]) : []')
            import_blocks.append(f'  to = okta_group_rule.rule_{env}_{rule_id}[0]')
            import_blocks.append(f'  id = "{rule_id}"')
            import_blocks.append('}')
            import_blocks.append('')

    return "\n".join(import_blocks)


###############################################################################
# 5. Main Program (Argument Parsing & Control Flow)
###############################################################################

def main():
    parser = argparse.ArgumentParser(description="Unified script for fetching Okta groups/rules & generating Terraform.")
    
    # Okta subdomain/domain & token
    parser.add_argument("--subdomain", help="Your Okta subdomain (e.g., yourcompany)")
    parser.add_argument("--domain", choices=["default", "emea", "preview", "gov", "mil"], default="default", help="Select Okta domain")
    parser.add_argument("--token", help="Okta API token (can also be set via OKTA_API_TOKEN env variable)")
    
    # Output CSVs for Okta fetches
    parser.add_argument("--groups_output", default="okta_groups_dynamic.csv", help="Output CSV for Okta Groups")
    parser.add_argument("--rules_output", default="okta_group_rules.csv", help="Output CSV for Okta Group Rules")
    
    # CSV paths for Terraform generation
    parser.add_argument("--prod_groups", type=str, help="File path for prod_groups CSV")
    parser.add_argument("--prod_rules", type=str, help="File path for prod_rules CSV")
    parser.add_argument("--preview_groups", type=str, help="File path for preview_groups CSV")
    parser.add_argument("--preview_rules", type=str, help="File path for preview_rules CSV")
    
    # Operation flags
    parser.add_argument("--fetch_okta_groups", action="store_true", help="Fetch groups from Okta (type=OKTA_GROUP) and export CSV")
    parser.add_argument("--fetch_okta_rules", action="store_true", help="Fetch group rules from Okta and export CSV")
    parser.add_argument("--generate_tf", action="store_true", help="Generate Terraform from CSV data")

    args = parser.parse_args()

    # Check or retrieve Okta API token
    api_token = args.token or os.getenv("OKTA_API_TOKEN")

    # If fetching from Okta, ensure we have subdomain & token
    if args.fetch_okta_groups or args.fetch_okta_rules:
        if not api_token:
            print("Error: API token must be provided (argument or OKTA_API_TOKEN).")
            return
        if not args.subdomain:
            print("Error: --subdomain is required when fetching from Okta.")
            return

        okta_domain = get_okta_domain(args.subdomain, args.domain)

        # 1) Fetch Okta Groups
        if args.fetch_okta_groups:
            groups = fetch_okta_groups(okta_domain, api_token)
            if groups:
                process_and_export_groups(groups, args.groups_output)
            else:
                print("No groups fetched or an error occurred.")

        # 2) Fetch Okta Group Rules
        if args.fetch_okta_rules:
            rules = fetch_okta_group_rules(okta_domain, api_token)
            if rules:
                process_and_export_rules(rules, args.rules_output)
            else:
                print("No rules fetched or an error occurred.")

    # If generating Terraform, do so from CSV paths
    if args.generate_tf:
        # Build dictionary of CSV file paths
        files = {
            "prod_groups": args.prod_groups,
            "prod_rules": args.prod_rules,
            "preview_groups": args.preview_groups,
            "preview_rules": args.preview_rules,
        }

        # Load CSV data for groups/rules
        group_data = {
            env: load_csv(files[f"{env}_groups"]) for env in ["preview", "prod"]
        }
        group_rule_data = {
            env: load_csv(files[f"{env}_rules"]) for env in ["preview", "prod"]
        }

        # Generate Terraform
        terraform_output = generate_terraform_resources(group_data, group_rule_data)
        import_output = generate_terraform_imports(group_data, group_rule_data)

        # Write to .tf files
        script_dir = os.path.dirname(os.path.abspath(__file__))
        combined_file = os.path.join(script_dir, "combined-terraform-output.tf")
        resource_file = os.path.join(script_dir, "generated-terraform.tf")
        import_file = os.path.join(script_dir, "terraform-imports.tf")

        with open(resource_file, "w") as rf:
            rf.write(terraform_output)

        with open(import_file, "w") as inf:
            inf.write(import_output)

        with open(combined_file, "w") as cf:
            cf.write(terraform_output)
            cf.write("\n\n")
            cf.write(import_output)

        print(f"Terraform resource file generated: {resource_file}")
        print(f"Terraform import file generated: {import_file}")
        print(f"Combined Terraform file generated: {combined_file}")

    # If no operations specified, show help
    if not any([args.fetch_okta_groups, args.fetch_okta_rules, args.generate_tf]):
        parser.print_help()

# -----------------------------------------------------------------------------
# 6. Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    main()