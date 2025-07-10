#!/usr/bin/env python3
import argparse
import requests
import json
import re
import time
import pandas as pd
import subprocess

# ----- Helper Functions -----

def get_okta_domain(subdomain, domain_flag):
    """Build the Okta domain URL using a subdomain and domain_flag."""
    domain_map = {
        "default": "okta.com",
        "emea": "okta-emea.com",
        "preview": "oktapreview.com",
        "gov": "okta-gov.com",
        "mil": "okta.mil"
    }
    domain = domain_map.get(domain_flag, "okta.com")
    return f"{subdomain}.{domain}"

def get_api_data(url, headers, retry_count=3):
    """Query an Okta API endpoint with basic rate-limit handling."""
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json(), response.headers
    elif response.status_code == 429:
        reset = response.headers.get("x-rate-limit-reset")
        if reset:
            current_time = time.time()
            sleep_time = int(reset) - current_time
            if sleep_time < 0:
                sleep_time = 1
            print(f"Rate limit reached. Sleeping for {sleep_time:.2f} seconds before retrying {url}.")
            time.sleep(sleep_time)
        else:
            print("Rate limit reached but no reset header found. Sleeping for 60 seconds.")
            time.sleep(60)
        if retry_count > 0:
            return get_api_data(url, headers, retry_count - 1)
        else:
            print(f"Retries exhausted for {url}")
            return None, response.headers
    else:
        print(f"Error: {response.status_code} when querying {url}")
        return None, response.headers

def normalize_resource_name(label):
    """Normalize a label to a valid Terraform resource name."""
    normalized = label.lower().replace(" ", "_")
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    if normalized and normalized[0].isdigit():
        normalized = "_" + normalized
    return normalized

def substitute_member(member, group_map, user_map, app_map=None, okta_domain=""):
    """
    Substitute a member URL with an environment-independent interpolation.
    Handles query filters and trailing segments.
    """
    if "apps?filter" in member:
        new_url = member.replace(f"https://{okta_domain}", "${local.org_url}")
        new_url = new_url.replace('"', '\\"')
        return new_url

    if member.endswith("/api/v1/groups"):
        return "${local.org_url}/api/v1/groups"
    if member.endswith("/api/v1/users"):
        return "${local.org_url}/api/v1/users"
    if member.endswith("/api/v1/apps"):
        return "${local.org_url}/api/v1/apps"

    # For groups
    group_pattern = r'/api/v1/groups/([^/]+)(/.*)?$'
    m_group = re.search(group_pattern, member)
    if m_group:
        gid = m_group.group(1)
        extra = m_group.group(2) if m_group.group(2) else ""
        if gid in group_map:
            normalized = group_map[gid]
            return '${local.org_url}/api/v1/groups/${data.okta_group.' + normalized + '.id}' + extra

    # For users:
    user_pattern = r'/api/v1/users/([^/]+)$'
    m_user = re.search(user_pattern, member)
    if m_user:
        uid = m_user.group(1)
        if uid in user_map:
            normalized = user_map[uid]
            return '${local.org_url}/api/v1/users/${data.okta_user.' + normalized + '.id}'
    # For apps:
    app_pattern = r'/api/v1/apps/([^/]+)(/.*)?$'
    m_app = re.search(app_pattern, member)
    if m_app:
        aid = m_app.group(1)
        extra = m_app.group(2) if m_app.group(2) else ""
        if app_map and aid in app_map:
            normalized = app_map[aid]
            return '${local.org_url}/api/v1/apps/${data.okta_app.' + normalized + '.id}' + extra
    return member.replace('"', '\\"')

# ----- Mapping Builders (using Pandas) -----

def build_group_mapping(groups):
    df = pd.DataFrame(groups)
    # Use profile.name if available; else fallback to "name"
    if "profile" in df.columns:
        # Some JSON may nest profile as a dict; if so, extract 'name'
        df["display"] = df["profile"].apply(lambda p: p.get("name") if isinstance(p, dict) and "name" in p else None)
    elif "name" in df.columns:
        df["display"] = df["name"]
    else:
        df["display"] = df["id"]
    df["display"] = df["display"].fillna(df["id"])
    df["normalized"] = df["display"].apply(normalize_resource_name)
    mapping = { row["id"]: row["normalized"] for _, row in df.iterrows() }
    return mapping

def build_user_mapping(users):
    df = pd.DataFrame(users)
    if "profile" in df.columns:
        df["display"] = df["profile"].apply(lambda p: p.get("email") if isinstance(p, dict) and "email" in p else None)
    elif "login" in df.columns:
        df["display"] = df["login"]
    else:
        df["display"] = df["id"]
    df["display"] = df["display"].fillna(df["id"])
    df["normalized"] = df["display"].apply(normalize_resource_name)
    mapping = { row["id"]: row["normalized"] for _, row in df.iterrows() }
    return mapping

def build_app_mapping(apps):
    df = pd.DataFrame(apps)
    if "label" in df.columns:
        df["display"] = df["label"].fillna(df["id"])
    elif "name" in df.columns:
        df["display"] = df["name"].fillna(df["id"])
    else:
        df["display"] = df["id"]
    df["normalized"] = df["display"].apply(normalize_resource_name)
    mapping = { row["id"]: row["normalized"] for _, row in df.iterrows() }
    return mapping

# ----- API Data Fetching Functions -----

def fetch_roles(okta_domain, headers):
    roles = []
    endpoint = f"https://{okta_domain}/api/v1/iam/roles"
    while endpoint:
        print(f"Fetching roles from: {endpoint}")
        data, _ = get_api_data(endpoint, headers)
        if not data:
            break
        roles.extend(data.get("roles", []))
        next_link = data.get("_links", {}).get("next", {}).get("href")
        endpoint = next_link if next_link else None
    return roles

def fetch_role_permissions(okta_domain, role_id, headers):
    endpoint = f"https://{okta_domain}/api/v1/iam/roles/{role_id}/permissions"
    print(f"Fetching permissions from: {endpoint}")
    data, _ = get_api_data(endpoint, headers)
    if data and "permissions" in data:
        return [perm.get("label") for perm in data["permissions"] if perm.get("label")]
    return []

def fetch_resource_sets(okta_domain, headers):
    resource_sets = []
    endpoint = f"https://{okta_domain}/api/v1/iam/resource-sets"
    while endpoint:
        print(f"Fetching resource sets from: {endpoint}")
        data, _ = get_api_data(endpoint, headers)
        if not data:
            break
        resource_sets.extend(data.get("resource-sets", []))
        next_link = data.get("_links", {}).get("next", {}).get("href")
        endpoint = next_link if next_link else None
    return resource_sets

def fetch_resource_set_resources(okta_domain, resource_set_id, headers):
    endpoint = f"https://{okta_domain}/api/v1/iam/resource-sets/{resource_set_id}/resources"
    print(f"Fetching resource set resources from: {endpoint}")
    data, _ = get_api_data(endpoint, headers)
    resources = []
    if data and "resources" in data:
        for res in data["resources"]:
            links = res.get("_links")
            if not links:
                print(f"DEBUG: Resource {res.get('id')} missing '_links'.")
                continue
            self_link_obj = links.get("self")
            if not self_link_obj:
                print(f"DEBUG: Resource {res.get('id')} missing 'self' link.")
                continue
            href = self_link_obj.get("href")
            if href:
                resources.append(href)
            else:
                print(f"DEBUG: Resource {res.get('id')} has 'self' but no 'href'.")
    else:
        print(f"DEBUG: No 'resources' key in response for resource set {resource_set_id}.")
    return resources

def fetch_all_groups(okta_domain, headers):
    groups = []
    endpoint = f"https://{okta_domain}/api/v1/groups"
    while endpoint:
        print(f"Fetching groups from: {endpoint}")
        resp = requests.get(endpoint, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            groups.extend(data)
            link_header = resp.headers.get("Link")
            next_url = None
            if link_header:
                links = re.findall(r'<([^>]+)>;\s*rel="next"', link_header)
                if links:
                    next_url = links[0]
            endpoint = next_url
        else:
            print(f"Error: {resp.status_code} when fetching groups from {endpoint}")
            break
    return groups

def fetch_all_users(okta_domain, headers):
    users = []
    endpoint = f"https://{okta_domain}/api/v1/users"
    while endpoint:
        print(f"Fetching users from: {endpoint}")
        resp = requests.get(endpoint, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            users.extend(data)
            link_header = resp.headers.get("Link")
            next_url = None
            if link_header:
                links = re.findall(r'<([^>]+)>;\s*rel="next"', link_header)
                if links:
                    next_url = links[0]
            endpoint = next_url
        else:
            print(f"Error: {resp.status_code} when fetching users from {endpoint}")
            break
    return users

def fetch_group_roles(okta_domain, group_id, headers):
    endpoint = f"https://{okta_domain}/api/v1/groups/{group_id}/roles"
    print(f"Fetching group roles for group {group_id} from: {endpoint}")
    data, _ = get_api_data(endpoint, headers)
    return data if data else []

def fetch_user_roles(okta_domain, user_id, headers):
    endpoint = f"https://{okta_domain}/api/v1/users/{user_id}/roles"
    print(f"Fetching user roles for user {user_id} from: {endpoint}")
    data, _ = get_api_data(endpoint, headers)
    return data if data else []

def fetch_apps(okta_domain, headers):
    apps = []
    endpoint = f"https://{okta_domain}/api/v1/apps"
    while endpoint:
        print(f"Fetching apps from: {endpoint}")
        data, hdrs = get_api_data(endpoint, headers)
        if not data:
            break
        apps.extend(data)
        link_header = hdrs.get("Link")
        next_url = None
        if link_header:
            links = re.findall(r'<([^>]+)>;\s*rel="next"', link_header)
            if links:
                next_url = links[0]
        endpoint = next_url
    return apps

# ----- Debugging with Pandas & CSV Output -----

def debug_with_pandas(resource_sets, roles, okta_domain, headers, tf_file, args, group_map, user_map, app_map):
    # Debug Resource Sets
    df_rs = pd.DataFrame(resource_sets)
    print("Resource Sets DataFrame:")
    if not df_rs.empty:
        print(df_rs[['id', 'label', 'description']].head())
        df_rs.to_csv("debug_resource_sets.csv", index=False)
        print("Resource sets CSV written to debug_resource_sets.csv")
    else:
        print("No resource sets data available.")
    
    # Debug IAM Roles
    df_roles = pd.DataFrame(roles)
    if not df_roles.empty:
        df_roles["normalized"] = df_roles["label"].apply(normalize_resource_name)
        print("IAM Roles DataFrame with Normalized Names:")
        print(df_roles[['id', 'label', 'normalized', 'description']].head())
        df_roles.to_csv("debug_iam_roles.csv", index=False)
        print("IAM roles CSV written to debug_iam_roles.csv")
    else:
        print("No roles data available.")
    
    # Debug Groups
    groups = fetch_all_groups(okta_domain, headers)
    df_groups = pd.DataFrame(groups)
    if not df_groups.empty:
        if "profile" in df_groups.columns:
            df_groups["display"] = df_groups["profile"].apply(lambda p: p.get("name") if isinstance(p, dict) and "name" in p else None)
        elif "name" in df_groups.columns:
            df_groups["display"] = df_groups["name"]
        else:
            df_groups["display"] = df_groups["id"]
        df_groups["display"] = df_groups["display"].fillna(df_groups["id"])
        df_groups["normalized"] = df_groups["display"].apply(normalize_resource_name)
        print("Groups DataFrame:")
        print(df_groups.head())
        df_groups.to_csv("debug_groups.csv", index=False)
        print("Groups CSV written to debug_groups.csv")
    else:
        print("No groups data available.")
    
    # Debug Users
    users = fetch_all_users(okta_domain, headers)
    df_users = pd.DataFrame(users)
    if not df_users.empty:
        if "profile" in df_users.columns:
            df_users["display"] = df_users["profile"].apply(lambda p: p.get("email") if isinstance(p, dict) and "email" in p else None)
        elif "login" in df_users.columns:
            df_users["display"] = df_users["login"]
        else:
            df_users["display"] = df_users["id"]
        df_users["display"] = df_users["display"].fillna(df_users["id"])
        df_users["normalized"] = df_users["display"].apply(normalize_resource_name)
        print("Users DataFrame:")
        print(df_users.head())
        df_users.to_csv("debug_users.csv", index=False)
        print("Users CSV written to debug_users.csv")
    else:
        print("No users data available.")
    
    # Debug Apps
    apps = fetch_apps(okta_domain, headers)
    df_apps = pd.DataFrame(apps)
    if not df_apps.empty:
        if "label" in df_apps.columns:
            df_apps["display"] = df_apps["label"].fillna(df_apps["id"])
        elif "name" in df_apps.columns:
            df_apps["display"] = df_apps["name"].fillna(df_apps["id"])
        else:
            df_apps["display"] = df_apps["id"]
        df_apps["normalized"] = df_apps["display"].apply(normalize_resource_name)
        print("Apps DataFrame:")
        print(df_apps.head())
        df_apps.to_csv("debug_apps.csv", index=False)
        print("Apps CSV written to debug_apps.csv")
    else:
        print("No apps data available.")
    
    # For groups and users, fetch roles.
    group_roles_by_group = {}
    for group in groups:
        gid = group.get("id")
        assignments = fetch_group_roles(okta_domain, gid, headers)
        if assignments:
            group_roles_by_group[gid] = assignments

    user_roles_by_user = {}
    for user in users:
        uid = user.get("id")
        assignments = fetch_user_roles(okta_domain, uid, headers)
        if assignments:
            user_roles_by_user[uid] = assignments

    # Generate Terraform blocks for group and user roles.
    generate_import_blocks_for_group_roles(group_roles_by_group, tf_file)
    generate_terraform_group_roles(group_roles_by_group, tf_file, args.terraform_format, group_map)
    generate_import_blocks_for_user_roles(user_roles_by_user, tf_file)
    generate_terraform_user_roles(user_roles_by_user, tf_file, args.terraform_format, user_map)

    return group_roles_by_group, user_roles_by_user

# ----- Data Blocks Generators -----

def generate_data_blocks_for_groups(groups, data_tf_file):
    with open(data_tf_file, "w") as f:
        f.write("# Generated Data Blocks for Okta Groups\n\n")
        for group in groups:
            group_id = group.get("id")
            # Prefer using the group's name from profile if available.
            if "profile" in group and isinstance(group["profile"], dict) and group["profile"].get("name"):
                group_name = group["profile"]["name"]
            elif "name" in group:
                group_name = group["name"]
            else:
                group_name = group_id
            normalized = normalize_resource_name(group_name)
            # Use the data source schema with "name" as a filter.
            block = f'''
data "okta_group" "{normalized}" {{
  name = "{group_name}"
}}
'''
            f.write(block)

def generate_data_blocks_for_users(users, data_tf_file):
    with open(data_tf_file, "a") as f:
        f.write("\n# Generated Data Blocks for Okta Users\n\n")
        for user in users:
            user_id = user.get("id")
            # Use profile.email if available.
            if "profile" in user and isinstance(user["profile"], dict) and user["profile"].get("email"):
                user_email = user["profile"]["email"]
            elif "login" in user:
                user_email = user["login"]
            else:
                user_email = user_id
            normalized = normalize_resource_name(user_email)
            block = f'''
data "okta_user" "{normalized}" {{
  search {{
    expression = "profile.email eq \\"{user_email}\\""
  }}
}}
'''
            f.write(block)

def generate_data_blocks_for_resource_sets(resource_sets, data_tf_file):
    with open(data_tf_file, "a") as f:
        f.write("\n# Generated Data Blocks for Okta Resource Sets\n\n")
        for rs in resource_sets:
            rs_id = rs.get("id")
            label = rs.get("label")
            normalized = normalize_resource_name(label)
            block = f'''
data "okta_resource_set" "{normalized}" {{
  id = "{rs_id}"
}}
'''
            f.write(block)

def generate_data_blocks_for_custom_roles(roles, data_tf_file):
    with open(data_tf_file, "a") as f:
        f.write("\n# Generated Data Blocks for Okta Custom Admin Roles\n\n")
        for role in roles:
            if role.get("id", "").startswith("cr"):
                role_id = role.get("id")
                label = role.get("label")
                normalized = normalize_resource_name(label)
                block = f'''
data "okta_admin_role_custom" "{normalized}" {{
  id = "{role_id}"
}}
'''
                f.write(block)

def generate_data_blocks_for_apps(app_map, data_tf_file):
    if not app_map:
        return
    with open(data_tf_file, "a") as f:
        f.write("\n# Generated Data Blocks for Okta Apps\n\n")
        for app_id, normalized in app_map.items():
            block = f'''
data "okta_app" "{normalized}" {{
  id = "{app_id}"
}}
'''
            f.write(block)

# ----- Terraform Resource Block Generators -----

def generate_terraform_roles(roles, tf_file, terraform_format, okta_domain, headers):
    with open(tf_file, "a") as f:
        f.write("\n# Terraform configuration for Okta IAM Admin Roles (okta_admin_role_custom)\n\n")
        for role in roles:
            role_id = role.get("id")
            label = role.get("label")
            description = role.get("description", "")
            permissions = fetch_role_permissions(okta_domain, role_id, headers)
            normalized_name = normalize_resource_name(label)
            if terraform_format == "hcl":
                perms_formatted = ", ".join([f'"{perm}"' for perm in permissions])
                block = f'''
resource "okta_admin_role_custom" "{normalized_name}" {{
  label       = "{label}"
  description = "{description}"
  permissions = [{perms_formatted}]
  
  tags = {{
    resource_id    = "{role_id}"
    resource_label = "{label}"
  }}
}}
'''
            else:
                block = json.dumps({
                    "resource": {
                        "okta_admin_role_custom": {
                            normalized_name: {
                                "label": label,
                                "description": description,
                                "permissions": permissions,
                                "tags": {
                                    "resource_id": role_id,
                                    "resource_label": label
                                }
                            }
                        }
                    }
                }, indent=2) + "\n"
            f.write(block)

def generate_terraform_resource_sets(resource_sets, tf_file, terraform_format, okta_domain, headers, group_map, user_map, app_map):
    with open(tf_file, "a") as f:
        f.write("\n# Terraform configuration for Okta Resource Sets (okta_resource_set)\n\n")
        for rs in resource_sets:
            rs_id = rs.get("id")
            label = rs.get("label")
            description = rs.get("description", "")
            endpoints = fetch_resource_set_resources(okta_domain, rs_id, headers)
            substituted_endpoints = [substitute_member(ep, group_map, user_map, app_map, okta_domain) for ep in endpoints]
            endpoints_formatted = ", ".join([f'"{ep}"' for ep in substituted_endpoints])
            normalized_name = normalize_resource_name(label)
            if terraform_format == "hcl":
                block = f'''
resource "okta_resource_set" "{normalized_name}" {{
  label       = "{label}"
  description = "{description}"
  resources   = [{endpoints_formatted}]
  
  tags = {{
    resource_id    = "{rs_id}"
    resource_label = "{label}"
  }}
}}
'''
            else:
                block = json.dumps({
                    "resource": {
                        "okta_resource_set": {
                            normalized_name: {
                                "label": label,
                                "description": description,
                                "resources": substituted_endpoints,
                                "tags": {
                                    "resource_id": rs_id,
                                    "resource_label": label
                                }
                            }
                        }
                    }
                }, indent=2) + "\n"
            f.write(block)

def generate_import_blocks_for_resource_sets(resource_sets, tf_file):
    with open(tf_file, "a") as f:
        f.write("\n# Import blocks for Okta Resource Sets\n")
        for rs in resource_sets:
            rs_id = rs.get("id")
            block = f'''
import {{
  for_each = var.CONFIG == "prod" ? toset(["prod"]) : []
  to       = okta_resource_set.{normalize_resource_name(rs.get("label", rs_id))}[0]
  id       = "{rs_id}"
}}
'''
            f.write(block)

def generate_import_blocks_for_admin_roles(roles, tf_file):
    with open(tf_file, "a") as f:
        f.write("\n# Import blocks for Okta IAM Admin Roles\n")
        for role in roles:
            role_id = role.get("id")
            block = f'''
import {{
  for_each = var.CONFIG == "prod" ? toset(["prod"]) : []
  to       = okta_admin_role_custom.{normalize_resource_name(role.get("label", role_id))}
  id       = "{role_id}"
}}
'''
            f.write(block)

def generate_terraform_custom_assignments(custom_assignments, tf_file, terraform_format, group_map, user_map, resource_set_map, custom_role_map, okta_domain):
    with open(tf_file, "a") as f:
        f.write("\n# Terraform configuration for Custom Role Assignments (okta_admin_role_custom_assignments)\n\n")
        for (custom_role_id, resource_set_id), members in custom_assignments.items():
            resource_name = f"ca_{normalize_resource_name(custom_role_id)}_{normalize_resource_name(resource_set_id)}"
            substituted_members = [substitute_member(m, group_map, user_map, okta_domain=okta_domain) for m in members]
            members_list = ", ".join([f'"{m}"' for m in substituted_members])
            if resource_set_id in resource_set_map:
                resource_set_reference = f"okta_resource_set.{resource_set_map[resource_set_id]}.id"
            else:
                resource_set_reference = f'"{resource_set_id}"'
            if custom_role_id in custom_role_map:
                custom_role_reference = f"okta_admin_role_custom.{custom_role_map[custom_role_id]}.id"
            else:
                custom_role_reference = f'"{custom_role_id}"'
            if terraform_format == "hcl":
                block = f'''
resource "okta_admin_role_custom_assignments" "{resource_name}" {{
  resource_set_id = {resource_set_reference}
  custom_role_id  = {custom_role_reference}
  members         = [{members_list}]
}}
'''
            else:
                block = json.dumps({
                    "resource": {
                        "okta_admin_role_custom_assignments": {
                            resource_name: {
                                "resource_set_id": resource_set_reference,
                                "custom_role_id": custom_role_reference,
                                "members": substituted_members
                            }
                        }
                    }
                }, indent=2) + "\n"
            f.write(block)

def generate_import_blocks_for_custom_assignments(custom_assignments, tf_file):
    with open(tf_file, "a") as f:
        f.write("\n# Import blocks for Custom Role Assignments\n")
        for (custom_role_id, resource_set_id) in custom_assignments.keys():
            resource_name = f"ca_{normalize_resource_name(custom_role_id)}_{normalize_resource_name(resource_set_id)}"
            block = f'''
import {{
  for_each = var.CONFIG == "prod" ? toset(["prod"]) : []
  to       = okta_admin_role_custom_assignments.{resource_name}
  id       = "{resource_set_id}/{custom_role_id}"
}}
'''
            f.write(block)

def generate_terraform_group_roles(group_roles_by_group, tf_file, terraform_format, group_map):
    with open(tf_file, "a") as f:
        f.write("\n# Terraform configuration for Standard Group Roles (okta_group_role)\n\n")
        for group_id, assignments in group_roles_by_group.items():
            if group_id in group_map:
                group_ref = f"data.okta_group.{group_map[group_id]}.id"
            else:
                group_ref = f'"{group_id}"'
            for assignment in assignments:
                if assignment.get("type") == "CUSTOM":
                    continue
                role_type = assignment.get("type")
                resource_name = f"group_{group_id}_{assignment.get('id')}"
                block = f'''
resource "okta_group_role" "{resource_name}" {{
  group_id  = {group_ref}
  role_type = "{role_type}"
  
  tags = {{
    resource_id    = "{assignment.get('id')}"
    resource_label = "{assignment.get('label', 'n/a')}"
  }}
}}
'''
                f.write(block)

def generate_import_blocks_for_group_roles(group_roles_by_group, tf_file):
    with open(tf_file, "a") as f:
        f.write("\n# Import blocks for Standard Group Roles\n")
        for group_id, assignments in group_roles_by_group.items():
            for assignment in assignments:
                if assignment.get("type") == "CUSTOM":
                    continue
                resource_name = f"group_{group_id}_{assignment.get('id')}"
                block = f'''
import {{
  for_each = var.CONFIG == "prod" ? toset(["prod"]) : []
  to       = okta_group_role.{resource_name}
  id       = "{assignment.get('id')}"
}}
'''
                f.write(block)

def generate_terraform_user_roles(user_roles_by_user, tf_file, terraform_format, user_map):
    with open(tf_file, "a") as f:
        f.write("\n# Terraform configuration for Standard User Admin Roles (okta_user_admin_roles)\n\n")
        for user_id, assignments in user_roles_by_user.items():
            standard_roles = [assignment.get("type") for assignment in assignments if assignment.get("type") != "CUSTOM"]
            if not standard_roles:
                continue
            roles_list = list(set(standard_roles))
            roles_formatted = ", ".join([f'"{r}"' for r in roles_list])
            if user_id in user_map:
                user_reference = f"data.okta_user.{user_map[user_id]}.id"
            else:
                user_reference = f'"{user_id}"'
            resource_name = f"user_{user_id}"
            block = f'''
resource "okta_user_admin_roles" "{resource_name}" {{
  user_id     = {user_reference}
  admin_roles = [{roles_formatted}]
  
  tags = {{
    resource_id    = {user_reference}
    resource_label = "User {user_map.get(user_id, user_id)}"
  }}
}}
'''
            f.write(block)

def generate_import_blocks_for_user_roles(user_roles_by_user, tf_file):
    with open(tf_file, "a") as f:
        f.write("\n# Import blocks for Standard User Admin Roles\n")
        for user_id, assignments in user_roles_by_user.items():
            standard_roles = [assignment.get("type") for assignment in assignments if assignment.get("type") != "CUSTOM"]
            if not standard_roles:
                continue
            resource_name = f"user_{user_id}"
            block = f'''
import {{
  for_each = var.CONFIG == "prod" ? toset(["prod"]) : []
  to       = okta_user_admin_roles.{resource_name}
  id       = "{user_id}"
}}
'''
            f.write(block)

def aggregate_custom_assignments(group_roles_by_group, user_roles_by_user):
    custom_assignments = {}
    for group_id, assignments in group_roles_by_group.items():
        for assignment in assignments:
            if assignment.get("type") == "CUSTOM":
                custom_role_id = assignment.get("role")
                resource_set_id = assignment.get("resource-set")
                key = (custom_role_id, resource_set_id)
                member_href = '${{local.org_url}}/api/v1/groups/{}'.format(group_id)
                custom_assignments.setdefault(key, set()).add(member_href)
    for user_id, assignments in user_roles_by_user.items():
        for assignment in assignments:
            if assignment.get("type") == "CUSTOM":
                custom_role_id = assignment.get("role")
                resource_set_id = assignment.get("resource-set")
                key = (custom_role_id, resource_set_id)
                member_href = '${{local.org_url}}/api/v1/users/{}'.format(user_id)
                custom_assignments.setdefault(key, set()).add(member_href)
    return custom_assignments

# ----- Main Function -----

def main():
    parser = argparse.ArgumentParser(description="Generate Terraform config from Okta API data.")
    parser.add_argument("--subdomain", required=True, help="Okta subdomain (e.g. mydomain)")
    parser.add_argument("--domain-flag", choices=["default", "emea", "preview", "gov", "mil"], default="default",
                        help="Domain flag to determine the Okta domain suffix")
    parser.add_argument("--api-token", help="Okta API token", required=True)
    parser.add_argument("--output-prefix", help="Prefix for the output Terraform file", default="okta")
    parser.add_argument("--terraform-format", choices=["hcl", "json"], default="hcl",
                        help="Output format for Terraform configuration (hcl or json)")
    parser.add_argument("--all-groups", action="store_true", help="Iterate over all groups to fetch group roles")
    parser.add_argument("--all-users", action="store_true", help="Iterate over all users to fetch user roles")
    parser.add_argument("--tf-fmt", action="store_true", help="Run 'terraform fmt' on the generated file")
    
    args = parser.parse_args()

    okta_domain = get_okta_domain(args.subdomain, args.domain_flag)
    print(f"Using Okta domain: {okta_domain}")

    headers = {
        "Authorization": f"SSWS {args.api_token}",
        "Accept": "application/json"
    }

    tf_file = f"{args.output_prefix}_resources.tf"
    data_tf_file = "data-admin.tf"

    with open(tf_file, "w") as f:
        f.write("""# Generated Terraform configuration for Okta resources

data "okta_org_metadata" "_" {}
locals {
  org_url = try(
    data.okta_org_metadata._.alternate,
    data.okta_org_metadata._.organization
  )
}

""")
    
    # Fetch roles, resource sets, and apps.
    roles = fetch_roles(okta_domain, headers)
    resource_sets = fetch_resource_sets(okta_domain, headers)
    apps = fetch_apps(okta_domain, headers)
    
    # Build lookup mappings using Pandas.
    groups = fetch_all_groups(okta_domain, headers)
    users = fetch_all_users(okta_domain, headers)
    group_id_to_normalized = build_group_mapping(groups)
    user_id_to_normalized = build_user_mapping(users)
    app_id_to_normalized = build_app_mapping(apps)
    
    # Export debug CSVs.
    pd.DataFrame(apps).to_csv("debug_apps.csv", index=False)
    print("Apps CSV written to debug_apps.csv")
    pd.DataFrame(groups).to_csv("debug_groups.csv", index=False)
    print("Groups CSV written to debug_groups.csv")
    pd.DataFrame(users).to_csv("debug_users.csv", index=False)
    print("Users CSV written to debug_users.csv")
    pd.DataFrame(resource_sets).to_csv("debug_resource_sets.csv", index=False)
    print("Resource sets CSV written to debug_resource_sets.csv")
    
    # Debug with Pandas.
    group_roles_by_group, user_roles_by_user = debug_with_pandas(
        resource_sets, roles, okta_domain, headers, tf_file, args,
        group_id_to_normalized, user_id_to_normalized, app_id_to_normalized
    )
    
    # Write import blocks for IAM roles and resource sets.
    generate_import_blocks_for_resource_sets(resource_sets, tf_file)
    generate_import_blocks_for_admin_roles(roles, tf_file)
    
    # Build lookup mappings for resource sets and custom roles.
    resource_set_map = { rs.get("id"): normalize_resource_name(rs.get("label"))
                         for rs in resource_sets }
    custom_role_map = { role.get("id"): normalize_resource_name(role.get("label"))
                        for role in roles if role.get("id", "").startswith("cr") }
    
    # Generate data blocks for data sources.
    generate_data_blocks_for_groups(groups, data_tf_file)
    generate_data_blocks_for_users(users, data_tf_file)
    generate_data_blocks_for_resource_sets(resource_sets, data_tf_file)
    generate_data_blocks_for_custom_roles(roles, data_tf_file)
    generate_data_blocks_for_apps(app_id_to_normalized, data_tf_file)
    
    # Aggregate custom assignments and generate custom assignment blocks.
    custom_assignments = aggregate_custom_assignments(group_roles_by_group, user_roles_by_user)
    generate_import_blocks_for_custom_assignments(custom_assignments, tf_file)
    generate_terraform_custom_assignments(custom_assignments, tf_file, args.terraform_format,
                                          group_id_to_normalized, user_id_to_normalized,
                                          resource_set_map, custom_role_map, okta_domain)
    
    # Generate main IAM role and resource set blocks.
    generate_terraform_roles(roles, tf_file, args.terraform_format, okta_domain, headers)
    generate_terraform_resource_sets(resource_sets, tf_file, args.terraform_format,
                                     okta_domain, headers, group_id_to_normalized, user_id_to_normalized, app_id_to_normalized)
    
    # Generate user admin roles using interpolation.
    generate_terraform_user_roles(user_roles_by_user, tf_file, args.terraform_format, user_id_to_normalized)
    
    # Optionally run 'terraform fmt' on the generated file.
    if args.tf_fmt:
        print("Running 'terraform fmt' on the generated file...")
        result = subprocess.run(["terraform", "fmt", tf_file], capture_output=True, text=True)
        if result.returncode == 0:
            print("terraform fmt completed successfully.")
        else:
            print("Error running terraform fmt:")
            print(result.stderr)

    print(f"Terraform configuration written to {tf_file}")
    print(f"Data blocks for groups, users, resource sets, custom roles, and apps written to {data_tf_file}")

if __name__ == "__main__":
    main()