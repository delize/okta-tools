#!/bin/bash

FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\.tf$')

if [ -z "$FILES" ]; then
    exit 0
fi

echo "Checking Okta Group Rules for unescaped double quotes in 'expression_value'..."

FAILED=0

for FILE in $FILES; do
    if grep -Pzo '(?s)resource\s+"okta_group_rule"\s+".+?"\s*{.*?expression_value\s*=\s*"([^"\\]*(?<!\\)")[^"\\]*"' "$FILE"; then
        echo "ERROR: Unescaped double quotes found in 'expression_value' in $FILE"
        FAILED=1
    fi
done

if [ $FAILED -eq 1 ]; then
    echo "Fix the errors before committing."
    exit 1
fi

exit 0