# Python Script Summary

## What This Does
- **Data Retrieval & Mapping:**
  - Queries multiple Okta API endpoints to fetch IAM roles, resource sets, groups, users, apps, group roles, and user roles.
  - Uses helper functions with rate-limit handling and retries to robustly query the Okta APIs.
  - Builds lookup mappings for groups, users, and apps using Pandas for later substitution in Terraform configurations.
  - Exports debug CSVs for resource sets, groups, users, apps, and IAM roles.

- **Terraform Configuration Generation:**
  - Generates Terraform resource blocks for:
    - IAM custom admin roles (`okta_admin_role_custom`)
    - Okta resource sets (`okta_resource_set`)
    - Custom role assignments (`okta_admin_role_custom_assignments`)
    - Standard group roles (`okta_group_role`)
    - Standard user admin roles (`okta_user_admin_roles`)
  - Creates corresponding import blocks for each resource to allow later Terraform state import.
  - Aggregates custom assignments from both group and user roles.
  - Generates data blocks for Okta groups, users, resource sets, custom roles, and apps, writing them to a separate file.

- **Post-Processing:**
  - Optionally runs `terraform fmt` on the generated Terraform resource file to ensure proper formatting.

## APIs It Calls
- **IAM Roles API:**  
  - Endpoint: `/api/v1/iam/roles`  
  - Fetches custom and standard admin roles.
- **Role Permissions API:**  
  - Endpoint: `/api/v1/iam/roles/{role_id}/permissions`
- **Resource Sets API:**  
  - Endpoint: `/api/v1/iam/resource-sets`  
  - Also fetches individual resource set resources.
- **Groups API:**  
  - Endpoint: `/api/v1/groups`  
  - Retrieves all groups (with pagination handling).
- **Users API:**  
  - Endpoint: `/api/v1/users`  
  - Retrieves all users (with pagination handling).
- **Group Roles API:**  
  - Endpoint: `/api/v1/groups/{group_id}/roles`
- **User Roles API:**  
  - Endpoint: `/api/v1/users/{user_id}/roles`
- **Apps API:**  
  - Endpoint: `/api/v1/apps`

## What the Arguments Are For
- **Domain & Authentication:**
  - `--subdomain`: Specifies the Okta subdomain (e.g., "mydomain"); required.
  - `--domain-flag`: Determines the Okta domain suffix (choices: `default`, `emea`, `preview`, `gov`, or `mil`; default is `default`).
  - `--api-token`: Okta API token for authentication; required.
- **Output & Formatting:**
  - `--output-prefix`: Prefix for the output Terraform file (default: "okta").
  - `--terraform-format`: Output format for Terraform configuration; choices are "hcl" or "json" (default is "hcl").
  - `--tf-fmt`: If specified, runs `terraform fmt` on the generated file.
- **Optional Iterations:**
  - `--all-groups`: When set, iterates over all groups to fetch their roles.
  - `--all-users`: When set, iterates over all users to fetch their roles.

## What the Terraform Generated File Will Look Like
- **Header & Locals:**
  - Begins with a header comment and a data block for `okta_org_metadata`.
  - Defines a local variable (`org_url`) based on the organization metadata for environment-independent URL interpolation.

- **Resource Blocks:**
  - **IAM Roles & Custom Admin Roles:**  
    - Resource blocks for `okta_admin_role_custom` with attributes like label, description, permissions, and tags.
  - **Resource Sets:**  
    - Blocks for `okta_resource_set` including label, description, and a list of substituted API endpoints.
  - **Custom Role Assignments:**  
    - Blocks for `okta_admin_role_custom_assignments` that assign members (with URLs substituted via lookup maps) to custom roles and resource sets.
  - **Group Roles:**  
    - Blocks for `okta_group_role` that assign standard roles to groups, referencing data blocks for groups.
  - **User Admin Roles:**  
    - Blocks for `okta_user_admin_roles` that assign standard admin roles to users, referencing user data blocks.

- **Import Blocks:**
  - Consolidated import blocks for each resource type are generated using conditional `for_each` (based on environment, typically "prod") to facilitate resource import into Terraform state.

- **Data Blocks:**
  - A separate file (e.g., `data-admin.tf`) is created containing data blocks for:
    - Okta groups (searched by name)
    - Okta users (searched by email)
    - Okta resource sets, custom roles, and apps (searched by ID or label)

- **File Output:**
  - The main Terraform resource configuration is written to a file named with the provided output prefix (e.g., `okta_resources.tf`).
  - Data blocks are written to a separate file (`data-admin.tf`).