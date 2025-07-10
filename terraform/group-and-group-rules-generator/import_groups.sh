#!/bin/bash

# Ensure the file path is provided
IMPORT_FILE="import-groups-legacy.txt"

if [[ ! -f "$IMPORT_FILE" ]]; then
  echo "Error: Import file '$IMPORT_FILE' not found."
  exit 1
fi

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --env) ENV="$2"; shift ;;  # Capture environment argument
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Validate environment selection
if [[ "$ENV" == "preview" ]]; then
  export TF_VAR_env="test"  # Use test for preview
elif [[ "$ENV" == "prod" ]]; then
  export TF_VAR_env="prod"
else
  echo "Usage: $0 --env [preview|prod]"
  exit 1
fi

# Check if the Terraform workspace exists before selecting it
if ! terraform workspace list | grep -qE "^\*? $TF_VAR_env\$"; then
  echo "Error: Terraform workspace '$TF_VAR_env' does not exist."
  exit 1
fi

terraform workspace select "$TF_VAR_env"

# Extract and run Terraform import commands
awk '/to = / {to=$3} /id = / {id=$3; print to, id}' "$IMPORT_FILE" | while read -r RESOURCE RESOURCE_ID; do

  # Remove quotes from RESOURCE and RESOURCE_ID
  RESOURCE=${RESOURCE//\"/}
  RESOURCE_ID=${RESOURCE_ID//\"/}

  # Ensure correct mapping
  if [[ "$RESOURCE" =~ ^okta_group\.group_preview_.* ]]; then
    if [[ "$TF_VAR_env" == "test" ]]; then
      echo "Importing resource: $RESOURCE with ID: $RESOURCE_ID"
      terraform import -ignore-remote-version "$RESOURCE" "$RESOURCE_ID"
    fi
  elif [[ "$RESOURCE" =~ ^okta_group\.group_prod_.* ]]; then
    if [[ "$TF_VAR_env" == "prod" ]]; then
      echo "Importing resource: $RESOURCE with ID: $RESOURCE_ID"
      terraform import -ignore-remote-version "$RESOURCE" "$RESOURCE_ID"
    fi
  else
    echo "Skipping $RESOURCE as it doesn't match expected patterns."
  fi
done

echo "Terraform import process completed."