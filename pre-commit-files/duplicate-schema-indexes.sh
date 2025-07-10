#!/bin/bash
set -e

# Get staged files from git that have been added to the index
staged_files=$(git diff --cached --name-only)

error_found=0

# Process each staged file that contains 'user-default-schema' or 'group-default-schema' in its name.
for file in $staged_files; do
  if [[ "$file" == *user-default-schema* || "$file" == *group-default-schema* ]]; then
    if [ -f "$file" ]; then
      # Use awk to scan the file for resource blocks and duplicate index values.
      awk '
      BEGIN {
          dup=0
      }
      # Detect start of a resource block for okta_user_schema_property or okta_group_schema_property.
      /^resource[[:space:]]+"(okta_user_schema_property|okta_group_schema_property)"/ {
          inblock=1
          if (match($0, /resource[[:space:]]+"(okta_user_schema_property|okta_group_schema_property)"[[:space:]]+"([^"]+)"/, arr)) {
              current_resource = arr[2]
          } else {
              current_resource = "unknown"
          }
          index_val = ""
          next
      }
      inblock {
          # If an index attribute is found, capture its value.
          if ($0 ~ /[[:space:]]*index[[:space:]]*=[[:space:]]*".*"/) {
              if (match($0, /index[[:space:]]*=[[:space:]]*"([^"]+)"/, idx)) {
                  index_val = idx[1]
              }
          }
          # End of resource block is assumed when a line contains only a closing brace.
          if ($0 ~ /^[[:space:]]*}/) {
              if (index_val != "") {
                  if (index_seen[index_val] == "") {
                      index_seen[index_val] = current_resource
                  } else {
                      print "ERROR: In file \"" FILENAME "\": duplicate index value \"" index_val "\" found in resource \"" index_seen[index_val] "\" and \"" current_resource "\"."
                      dup=1
                  }
              }
              inblock=0
          }
      }
      END {
          if (dup == 1) exit 1
      }
      ' "$file" || { error_found=1; }
    fi
  fi
done

if [ "$error_found" -eq 1 ]; then
  echo "Pre-commit hook failed: Duplicate index values detected."
  exit 1
fi

exit 0