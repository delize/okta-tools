# What is this?

This generator will generate resource and import blocks, using imports in a per environment setup, so that you don't have to write 1000s of resources in Terraform Manually.

# How to use

## Initial Steps

1. Use `groups.py` and `group-rules.py` to generate the necessary files from the API for each environment (EG: `preview` and `production`)
2. (Optional) If you have any pre-existing Terraformed Resources, you can exclude them from the CSV files that were generated
3. Run `terraform-generator.py` to create a terraform file that contains:
   1. Import Resource Blocks
   2. Groups
   3. Group Rules
4. Run `terraform fmt` and `terraform validate`, if necessary to verify that the file is working correctly
5. Run `terraform plan`, then subsequently run `terraform apply`

## Group Resource Usage

```bash
$ python3 group-and-group-rules-generator/groups.py --help                                                                                                                             [22:12:49]
usage: groups.py [-h] --subdomain SUBDOMAIN [--domain {default,emea,preview,gov,mil}] [--token TOKEN] [--output OUTPUT]

Export Okta Groups to CSV with Dynamic Headers

options:
  -h, --help            show this help message and exit
  --subdomain SUBDOMAIN
                        Your Okta subdomain (e.g., yourcompany)
  --domain {default,emea,preview,gov,mil}
                        Select Okta domain
  --token TOKEN         Okta API token (can also be set via OKTA_API_TOKEN env variable)
  --output OUTPUT       Output CSV file
```
## Group Rules Resource Usage


```bash
$ python3 group-and-group-rules-generator/group-rules.py --help                                                                                                                        [22:20:13]
usage: group-rules.py [-h] --subdomain SUBDOMAIN [--domain {default,emea,preview,gov,mil}] [--token TOKEN] [--output OUTPUT]

Export Okta Group Rules to CSV with Dynamic Headers

options:
  -h, --help            show this help message and exit
  --subdomain SUBDOMAIN
                        Your Okta subdomain (e.g., yourcompany)
  --domain {default,emea,preview,gov,mil}
                        Select Okta domain
  --token TOKEN         Okta API token (can also be set via OKTA_API_TOKEN env variable)
  --output OUTPUT       Output CSV file
```



# Python Script Summary

## What This Does
- **Unified Workflow for Okta Groups and Rules:**
  - **Fetching Data from Okta:**
    - Retrieves Okta groups (filtered by type "OKTA_GROUP") and group rules via Okta API endpoints using pagination.
  - **Data Processing & CSV Export:**
    - Processes the fetched group and rule data dynamically.
    - Exports the processed groups to a CSV file (default: `okta_groups_dynamic.csv`).
    - Exports the processed group rules to a CSV file (default: `okta_group_rules.csv`).
  - **Terraform Configuration Generation:**
    - Loads CSV data (for both production and preview environments) and generates Terraform resource blocks for Okta groups and group rules.
    - Produces separate Terraform files for resources, import blocks, and a combined file.

## APIs It Calls
- **Okta Groups API:**
  - **Endpoint:** `/api/v1/groups`
  - **Method:** GET
  - **Headers:**  
    - `Authorization: SSWS {api_token}`
    - `Accept: application/json`
  - **Purpose:** Fetch all groups and filter to include only groups of type "OKTA_GROUP".
- **Okta Group Rules API:**
  - **Endpoint:** `/api/v1/groups/rules`
  - **Method:** GET
  - **Headers:**  
    - `Authorization: SSWS {api_token}`
    - `Accept: application/json`
  - **Purpose:** Fetch all group rules with pagination support.

## What the Arguments Are For
- **Domain & Authentication:**
  - `--subdomain`: Your Okta subdomain (e.g., "yourcompany").
  - `--domain`: Domain flag selection (choices: `default`, `emea`, `preview`, `gov`, or `mil`; default is `default`).
  - `--token`: Okta API token; can alternatively be provided via the `OKTA_API_TOKEN` environment variable.
- **CSV Output Paths:**
  - `--groups_output`: File path for the exported Okta Groups CSV.
  - `--rules_output`: File path for the exported Okta Group Rules CSV.
- **Terraform CSV Input Paths:**
  - `--prod_groups`, `--prod_rules`: CSV file paths for production environment groups and rules.
  - `--preview_groups`, `--preview_rules`: CSV file paths for preview environment groups and rules.
- **Operation Flags:**
  - `--fetch_okta_groups`: Flag to fetch groups from Okta and export them to CSV.
  - `--fetch_okta_rules`: Flag to fetch group rules from Okta and export them to CSV.
  - `--generate_tf`: Flag to generate Terraform configuration files from CSV data.

## What the Terraform Generated File Will Look Like
- **Terraform Resource Blocks for Okta Groups:**
  - Creates a resource block (`okta_group`) for each group.
  - Includes attributes such as name, description, custom profile attributes (like `adminNotes`, `groupDynamic`, and `groupOwner`), and a lifecycle block.
  - Uses a conditional count based on the environment (e.g., `prod` or `preview`).
- **Terraform Resource Blocks for Okta Group Rules:**
  - Generates resource blocks (`okta_group_rule`) for each rule.
  - Attributes include rule name, status, group assignments, expression type/value, and users excluded.
  - Uses a conditional count based on the environment.
- **Import Blocks:**
  - For each resource (both groups and rules), import blocks are created to link the Terraform resource with its Okta ID.
  - These blocks use conditional expressions (based on environment) to determine which resources to import.
- **Output Files:**
  - Separate Terraform files are produced:
    - One for resource blocks (e.g., `generated-terraform.tf`).
    - One for import blocks (e.g., `terraform-imports.tf`).
    - A combined file (`combined-terraform-output.tf`) that concatenates both sections.