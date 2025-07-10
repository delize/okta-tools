import json
import os
import pandas as pd
import re

# Get the script directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# File names (relative to the script directory)
files = {
    "prod_groups": "prod-groups-export.csv",
    "prod_rules": "prod-group-rules-export.csv",
    "preview_groups": "preview-groups-export.csv",
    "preview_rules": "preview-group-rules-export.csv",
}

# Function to load CSV data
def load_csv(filename):
    """Load CSV file from the script's directory, handling missing files gracefully."""
    file_path = os.path.join(script_dir, filename)
    if not os.path.exists(file_path):
        print(f"Warning: File not found: {file_path}. Returning empty DataFrame.")
        return pd.DataFrame()  # Return empty DataFrame instead of crashing
    return pd.read_csv(file_path)

# Function to clean values for Terraform
def clean_value(value, default=None):
    if pd.isna(value) or value == "Not Available" or value == "None":
        return default
    return value.replace('\n', ' ') if isinstance(value, str) else value

# Function to escape double quotes for Terraform resources
def escape_for_terraform_resources(value):
    if value:
        return value.replace('"', '\\"')  # Ensure single escaped quotes for Terraform resources
    return value

# Function to fix logical operator replacements (but only standalone, avoid breaking valid expressions)
def fix_logical_operators(value):
    if not value:
        return value
    
    # Preserve correctly formatted logical operators and avoid replacing already valid ones
    value = re.sub(r'(?<!\|)\|(?!\|)', '||', value)  # Replace standalone | with ||
    value = re.sub(r'(?<!&)\&(?!&)', '&&', value)  # Replace standalone & with &&
    return value

# Load data
group_data = {env: load_csv(files[f"{env}_groups"]) for env in ["preview", "prod"]}
group_rule_data = {env: load_csv(files[f"{env}_rules"]) for env in ["preview", "prod"]}

# Environment mapping
env_map = {"preview": "test", "prod": "prod"}

# Process groups
terraform_resources = []
terraform_imports = []

for env, df in group_data.items():
    env_key = env_map[env]
    
    for _, row in df.iterrows():
        group_id = row["id"]
        group_name = clean_value(row["name"], default="Unknown Group")

        terraform_resources.append(f"""
resource "okta_group" "group_{env}_{group_id}" {{
  count = var.CONFIG == "{env_map[env]}" ? 1 : 0
  name        = "{escape_for_terraform_resources(group_name)}"
  description = "{escape_for_terraform_resources(clean_value(row.get('description'), default='null'))}"
  custom_profile_attributes = jsonencode({{
    "admin_notes" = "{escape_for_terraform_resources(clean_value(row.get('adminNotes'), default='null'))}",
    "groupDynamic" = {json.dumps(clean_value(row.get('groupDynamic'), default=False))},
    "groupOwner" = "{escape_for_terraform_resources(clean_value(row.get('groupOwner'), default='null'))}"
  }})

  lifecycle {{
    ignore_changes = [skip_users]
  }}
}}
""")

        terraform_imports.append(f"""
import {{
  for_each = var.CONFIG == "{env_map[env]}" ? toset(["{env_map[env]}"]) : []
  to = okta_group.group_{env}_{group_id}[0]
  id = "{group_id}"
}}
""")

# Process group rules
for env, df in group_rule_data.items():
    
    for _, row in df.iterrows():
        rule_id = row["id"]
        rule_name = clean_value(row["name"], default="Unknown Rule")
        group_assignments = row["groupIds"].split(",")
        expression_value = fix_logical_operators(row["value"])
        expression_value = escape_for_terraform_resources(expression_value)
        expression_value = " ".join(expression_value.splitlines())  # Ensure it remains a single line
        terraform_resources.append(f"""
resource "okta_group_rule" "rule_{env}_{rule_id}" {{
  count = var.CONFIG == "{env_map[env]}" ? 1 : 0
  name   = "{escape_for_terraform_resources(rule_name)}"
  group_assignments = {json.dumps(group_assignments)}
  expression_type  = "urn:okta:expression:1.0"
  expression_value = "{expression_value}"
  users_excluded   = []
}}
""")

        terraform_imports.append(f"""
import {{
  for_each = var.CONFIG == "{env_map[env]}" ? toset(["{env_map[env]}"]) : []
  to = okta_group_rule.rule_{env}_{rule_id}[0]
  id = "{rule_id}"
}}
""")

# Write Terraform output
terraform_output = f"""
{''.join(terraform_resources)}

{''.join(terraform_imports)}
"""

# Save to Terraform file
output_file = os.path.join(script_dir, "groups-legacy-2024-v7.tf")
with open(output_file, "w") as f:
    f.write(terraform_output)

print(f"Terraform file generated: {output_file}")
