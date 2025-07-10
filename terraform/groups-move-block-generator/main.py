import sys
import re

def generate_move_blocks(input_path, output_path):
    # Read the entire input Terraform file.
    with open(input_path, "r") as f:
        content = f.read()

    # Regex pattern to capture okta_group resource blocks.
    # It captures:
    #   group ID (including preview or prod designation),
    #   the type (preview or prod),
    #   and the block content.
    pattern = r'resource\s+"okta_group"\s+"(group_(preview|prod)_[^"]+)"\s*\{(.*?)\n\}'
    
    preview_groups = {}
    prod_groups = {}

    # Use re.finditer so we can capture the match position (for line numbers).
    for match in re.finditer(pattern, content, re.DOTALL):
        full_resource = match.group(1)  # e.g., group_preview_00gzmnvlseYLlSaSP0h7
        kind = match.group(2)           # either "preview" or "prod"
        block = match.group(3)          # content of the resource block
        # Calculate the line number of the start of this match.
        line_num = content.count("\n", 0, match.start()) + 1

        # Look for the "name" attribute inside the block.
        name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
        if name_match:
            group_name = name_match.group(1).strip()
            if kind == "preview":
                preview_groups[group_name] = (full_resource, line_num)
            elif kind == "prod":
                prod_groups[group_name] = (full_resource, line_num)

    # For each preview group that has a matching production group (by the "name" attribute)
    # generate the move block.
    output_lines = []
    for group_name, (preview_id, preview_line) in preview_groups.items():
        if group_name in prod_groups:
            prod_id, prod_line = prod_groups[group_name]
            output_lines.append("moved {")
            output_lines.append(f"# Preview line {preview_line}, Prod line {prod_line}")
            output_lines.append(f"  from = okta_group.{preview_id}")
            output_lines.append(f"  to   = okta_group.{prod_id}")
            output_lines.append("}")
            output_lines.append("")  # Blank line for readability

    # Write the generated moved blocks to the output file.
    with open(output_path, "w") as out:
        out.write("\n".join(output_lines))
    print(f"Generated move blocks written to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python generate_move_blocks.py input_file output_file")
        sys.exit(1)
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    generate_move_blocks(input_file, output_file)