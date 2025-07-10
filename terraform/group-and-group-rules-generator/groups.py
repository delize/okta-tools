import requests
import csv
import os
import argparse

def get_okta_domain(subdomain, domain_flag):
    domain_map = {
        "default": "okta.com",
        "emea": "okta-emea.com",
        "preview": "oktapreview.com",
        "gov": "okta-gov.com",
        "mil": "okta.mil"
    }
    domain = domain_map.get(domain_flag, "okta.com")
    return f"https://{subdomain}.{domain}"

def fetch_okta_groups(okta_domain, api_token):
    """Fetch all groups from Okta API with pagination, filtering only OKTA_GROUP types."""
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
        groups.extend([group for group in data if group.get("type") == "OKTA_GROUP"])

        url = None
        if "link" in response.headers:
            links = response.headers["link"].split(", ")
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find("<") + 1: link.find(">")]
    
    return groups

def process_and_export_groups(groups, output_csv="okta_groups_dynamic.csv"):
    """Process group data dynamically and export it to CSV."""
    
    # Collect all possible headers dynamically
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
            row = {"id": group["id"]}  # ID is mandatory, no fallback needed
            
            for key in headers:
                if key == "id":
                    continue
                value = profile.get(key)
                if isinstance(value, bool):
                    row[key] = value  # Keep actual booleans as is
                elif isinstance(value, str):
                    stripped_value = value.strip()
                    if stripped_value.lower() in ["true", "false"]:
                        row[key] = stripped_value.lower() == "true"  # Convert "true" to True, "false" to False
                    else:
                        row[key] = stripped_value if stripped_value else None  # Keep as string or None
                else:
                    row[key] = None  # Default for other types
            
            writer.writerow(row)
    
    print(f"CSV file '{output_csv}' has been created successfully.")

def main():
    parser = argparse.ArgumentParser(description="Export Okta Groups to CSV with Dynamic Headers")
    parser.add_argument("--subdomain", required=True, help="Your Okta subdomain (e.g., yourcompany)")
    parser.add_argument("--domain", choices=["default", "emea", "preview", "gov", "mil"], default="default", help="Select Okta domain")
    parser.add_argument("--token", help="Okta API token (can also be set via OKTA_API_TOKEN env variable)")
    parser.add_argument("--output", default="okta_groups_dynamic.csv", help="Output CSV file")
    
    args = parser.parse_args()
    
    api_token = args.token or os.getenv("OKTA_API_TOKEN")
    if not api_token:
        print("Error: API token must be provided either as an argument or via the OKTA_API_TOKEN environment variable.")
        exit(1)
    
    okta_domain = get_okta_domain(args.subdomain, args.domain)
    groups = fetch_okta_groups(okta_domain, api_token)
    if groups:
        process_and_export_groups(groups, args.output)

if __name__ == "__main__":
    main()
