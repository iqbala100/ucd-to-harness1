import os
import yaml
from deepdiff import DeepDiff

# Input and output directories
input_dir = r"C:\Users\iqahmad\Desktop\RFP\GitHubRepo\ucd-to-harness1\harness_out_SU\.harness\services"
#input_dir = r"C:\Users\iqahmad\Desktop\RFP\GitHubRepo\ucd-to-harness1\harness_out_RG2\.harness\services"
output_dir = r"C:\Users\iqahmad\Desktop\RFP\GitHubRepo\ucd-to-harness1\yaml_diffs_SU"

# Ensure output directory exists
os.makedirs(output_dir, exist_ok=True)

# Get all YAML files from input directory
yaml_files = [f for f in os.listdir(input_dir) if f.endswith((".yaml", ".yml"))]

def load_yaml(file_path):
    with open(file_path, "r") as f:
        return yaml.safe_load(f)

def find_matches(dict1, dict2):
    """Return common key-value pairs between two dictionaries."""
    matches = {}
    for k, v in dict1.items():
        if k in dict2 and dict2[k] == v:
            matches[k] = v
    return matches

for i in range(len(yaml_files)):
    for j in range(i + 1, len(yaml_files)):
        file1 = yaml_files[i]
        file2 = yaml_files[j]

        data1 = load_yaml(os.path.join(input_dir, file1)) or {}
        data2 = load_yaml(os.path.join(input_dir, file2)) or {}

        # Find differences
        diff = DeepDiff(data1, data2, ignore_order=True)

        # Find matches
        matches = find_matches(data1 if isinstance(data1, dict) else {},
                               data2 if isinstance(data2, dict) else {})

        # Write output
        output_file = os.path.join(output_dir, f"compare_{file1}_vs_{file2}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"=== Comparison between {file1} and {file2} ===\n\n")

            if matches:
                f.write("✅ Matching values:\n")
                for k, v in matches.items():
                    f.write(f"   {k}: {v}\n")
            else:
                f.write("No matching values found.\n")

            f.write("\n❌ Differences:\n")
            if diff:
                f.write(str(diff))
            else:
                f.write("No differences found.\n")

print(f"Comparison completed. Results saved in: {output_dir}")