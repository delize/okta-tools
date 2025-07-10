import json
import os
import pandas as pd
import re
import argparse

# Get the script directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# File names (relative to the script directory)
def parse_arguments():
    parser = argparse.ArgumentParser(description="Specify file paths for different exports.")

    parser.add_argument("--prod_groups", type=str, help="File path for prod_groups")
    parser.add_argument("--prod_rules", type=str, help="File path for prod_rules")
    parser.add_argument("--preview_groups", type=str, help="File path for preview_groups")
    parser.add_argument("--preview_rules", type=str, help="File path for preview_rules")

    args = parser.parse_args()

    files = {
        "prod_groups": args.prod_groups,
        "prod_rules": args.prod_rules,
        "preview_groups": args.preview_groups,
        "preview_rules": args.preview_rules,
    }

    # Check existence and warn instead of exiting
    for name, path in files.items():
        if path and not os.path.exists(path):
            print(f"Warning: The specified file '{path}' for {name} does not exist. The script will proceed with an empty dataset.")

    return files

# Function to load CSV data
def load_csv(filename):
    """Load CSV file from the script's directory, handling missing files gracefully."""
    file_path = os.path.join(script_dir, filename)
    if not os.path.exists(file_path):
        print(f"Warning: File not found: {file_path}. Returning empty DataFrame.")
        return pd.DataFrame()
    return pd.read_csv(file_path)

# Function to handle boolean values for groupDynamic
def process_group_dynamic(value):
    """Ensure groupDynamic is properly formatted as a boolean or null."""
    if isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, str):
        value = value.strip().lower()
        if value in ["true", '"true"']:
            return "true"
        elif value in ["false", '"false"']:
            return "false"
        elif value in ["undefined", "none", "null", '"undefined"', '"none"', '"null"', "this is an invalid field"]:
            return "null"
    return "null"

# Function to ensure Terraform-compatible lists
def format_list(value):
    """Ensures a value is correctly formatted as a Terraform-compatible list."""
    if isinstance(value, list):
        return json.dumps(value)
    elif isinstance(value, str):
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            return value  # Already a list format
        elif value:
            return json.dumps([value])  # Wrap single values in a list
    return "[]"  # Default to an empty list

# Function to ensure Terraform-compatible lists for users_excluded
def format_users_excluded(value):
    """Ensures users_excluded is always an empty array."""
    return "[]"

# Function to clean values for Terraform
def clean_value(value, default=None):
    """Ensure proper handling of null values for Terraform."""
    if pd.isna(value) or value in ["Not Available", "None", "null"]:
        return None
    return value.replace('\n', ' ') if isinstance(value, str) else value

# Function to escape double quotes for Terraform resources
def escape_for_terraform_resources(value):
    if value:
        return value.replace('"', '\\"')
    return value

# Function to ensure Terraform-compatible lists for group_assignments
def format_group_assignments(value):
    """Ensures group_assignments is correctly formatted as a Terraform-compatible list."""
    if isinstance(value, list):
        return json.dumps(value)
    elif isinstance(value, str):
        value = value.strip()
        if "," in value:
            return json.dumps(value.split(","))
        elif value:
            return json.dumps([value])
    return "[]"

# Initialize the files dictionary by parsing command-line arguments.
files = parse_arguments()

# Load group and rule data using the files dictionary.
group_data = {env: load_csv(files[f"{env}_groups"]) for env in ["preview", "prod"]}
group_rule_data = {env: load_csv(files[f"{env}_rules"]) for env in ["preview", "prod"]}

# Function to generate Terraform resource blocks
def generate_terraform_resources(group_data, group_rule_data):
    terraform_config = []
    
    for env, groups in group_data.items():
        for _, group in groups.iterrows():
            group_name = escape_for_terraform_resources(clean_value(group.get("name")))
            group_id = clean_value(group.get("id"))
            group_description = clean_value(group.get("description"))
            adminNotes = clean_value(group.get("adminNotes"))
            group_dynamic = process_group_dynamic(group.get("groupDynamic"))
            group_owner = clean_value(group.get("groupOwner"))
            
            terraform_config.append(f'resource "okta_group" "group_{env}_{group_id}" {{')
            terraform_config.append(f'  count = var.CONFIG == "{env}" ? 1 : 0')
            terraform_config.append(f'  name        = "{group_name}"')
            terraform_config.append(f'  description = {json.dumps(group_description) if group_description else "null"}')
            terraform_config.append(f'  custom_profile_attributes = jsonencode({{')
            terraform_config.append(f'    "adminNotes" = {json.dumps(adminNotes) if adminNotes else "null"},')
            terraform_config.append(f'    "groupDynamic" = {group_dynamic},')
            terraform_config.append(f'    "groupOwner" = {json.dumps(group_owner) if group_owner else "null"}')
            terraform_config.append(f'  }})')
            terraform_config.append(f'  lifecycle {{ ignore_changes = [skip_users] }}')
            terraform_config.append("}")
            terraform_config.append("")
    
    for env, rules in group_rule_data.items():
        for _, rule in rules.iterrows():
            rule_id = clean_value(rule.get("id"))
            rule_name = escape_for_terraform_resources(clean_value(rule.get("name")))
            group_assignments = format_group_assignments(clean_value(rule.get("groupIds", [])))
            # users_excluded = format_users_excluded(clean_value(rule.get("excludedUsers", [])))
            users_excluded = format_users_excluded(clean_value(rule.get("excludedUsers", [])))
            status = rule.get("status", [])
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
            terraform_config.append("}")
            terraform_config.append("")
    
    return "\n".join(terraform_config)

# Function to generate Terraform import blocks
def generate_terraform_imports(group_data, group_rule_data):
    import_blocks = []
    for env, groups in group_data.items():
        for _, group in groups.iterrows():
            group_id = clean_value(group.get("id"))
            import_blocks.append(f'import {{')
            import_blocks.append(f'  for_each = var.CONFIG == "{env}" ? toset(["{env}"]) : []')
            import_blocks.append(f'  to = okta_group.group_{env}_{group_id}[0]')
            import_blocks.append(f'  id = "{group_id}"')
            import_blocks.append(f'}}')
            import_blocks.append("")
    
    for env, rules in group_rule_data.items():
        for _, rule in rules.iterrows():
            rule_id = clean_value(rule.get("id"))
            import_blocks.append(f'import {{')
            import_blocks.append(f'  for_each = var.CONFIG == "{env}" ? toset(["{env}"]) : []')
            import_blocks.append(f'  to = okta_group_rule.rule_{env}_{rule_id}[0]')
            import_blocks.append(f'  id = "{rule_id}"')
            import_blocks.append(f'}}')
            import_blocks.append("")
    
    return "\n".join(import_blocks)

# Generate Terraform configuration
terraform_output = generate_terraform_resources(group_data, group_rule_data)
import_output = generate_terraform_imports(group_data, group_rule_data)

# Define file paths
combined_file = os.path.join(script_dir, "groups-legacy-2024-v10.tf")
resource_file = os.path.join(script_dir, "generated-terraform.tf")
import_file = os.path.join(script_dir, "terraform-imports.tf")

# Write Terraform resources to separate file
with open(resource_file, "w") as f:
    f.write(terraform_output)

# Write Terraform imports to separate file
with open(import_file, "w") as f:
    f.write(import_output)

# Write a combined Terraform file (resources + imports)
with open(combined_file, "w") as f:
    f.write(terraform_output)
    f.write("\n\n")  # Separate resources and imports
    f.write(import_output)

print(f"Terraform resource file generated: {resource_file}")
print(f"Terraform import file generated: {import_file}")
print(f"Combined Terraform file generated: {combined_file}")