import json
import re
import os

def normalize_tag(tag):
    """Clean and unify tag names: remove non-alphanumeric characters and lowercase."""
    if not isinstance(tag, str):
        return tag
    return re.sub(r'[^a-zA-Z0-9]', '', tag).lower()

def normalize_merged_pid(input_json_path, output_path="normalized_merged_pid.json"):
    # Load JSON file
    with open(input_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Get all pipeline tags so we can skip normalization for them
    all_pipeline_tags = set(data.get("complete_pipeline_flows", {}).keys())
    print(f"🔍 Found {len(all_pipeline_tags)} pipeline tags. They will NOT be normalized.")

    # Helper: recursively normalize everything except pipeline tags
    def recursive_normalize(obj, skip_keys=("pipeline_tag",)):
        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                # Skip keys like "pipeline_tag"
                if k in skip_keys:
                    new_obj[k] = v
                    continue
                # Normalize strings unless they are known pipeline tags
                if isinstance(v, str):
                    if v in all_pipeline_tags:
                        new_obj[k] = v  # leave it as-is
                    else:
                        new_obj[k] = normalize_tag(v)
                else:
                    new_obj[k] = recursive_normalize(v, skip_keys)
            return new_obj

        elif isinstance(obj, list):
            new_list = []
            for item in obj:
                if isinstance(item, str):
                    if item in all_pipeline_tags:
                        new_list.append(item)  # keep pipeline tag
                    else:
                        new_list.append(normalize_tag(item))
                else:
                    new_list.append(recursive_normalize(item, skip_keys))
            return new_list

        else:
            return obj

    # ------------------------------
    # Normalize only non-pipeline tags
    # ------------------------------
    flow_data = data.get("complete_pipeline_flows", {})
    normalized_flows = {}

    for pipe_tag, pipe_info in flow_data.items():
        # Keep pipeline tag original
        normalized_flows[pipe_tag] = recursive_normalize(pipe_info, skip_keys=("pipeline_tag",))

    # ------------------------------
    # Normalize process_data tags
    # ------------------------------
    process_data = data.get("process_data", {})

    def normalize_tag_in_records(records, tag_field="Tag"):
        new_records = []
        for rec in records:
            rec_copy = dict(rec)
            if tag_field in rec_copy:
                tag_value = rec_copy[tag_field]
                if isinstance(tag_value, str) and tag_value not in all_pipeline_tags:
                    rec_copy[tag_field] = normalize_tag(tag_value)
            new_records.append(rec_copy)
        return new_records

    if "Equipment" in process_data:
        process_data["Equipment"] = normalize_tag_in_records(process_data["Equipment"])
    if "Instrumentation" in process_data:
        process_data["Instrumentation"] = normalize_tag_in_records(process_data["Instrumentation"])
    if "HandValves" in process_data:
        process_data["HandValves"] = normalize_tag_in_records(process_data["HandValves"])

    # ------------------------------
    # Build final normalized JSON
    # ------------------------------
    normalized_json = {
        "complete_pipeline_flows": normalized_flows,
        "process_data": process_data
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized_json, f, ensure_ascii=False, indent=2)

    print("✅ Normalization complete.")
    print("✅ All tags normalized except any pipeline tag (wherever found).")
    print(f"✅ Output saved as: {output_path}")

# Example usage
if __name__ == "__main__":
    input_file = "merged_pid_core.json"
    normalize_merged_pid(input_file, "normalized_merged_pid2.json")
