import json
from difflib import SequenceMatcher

def similarity(a, b):
    """Compute similarity ratio between two strings."""
    return SequenceMatcher(None, a, b).ratio()

def classify_tags_preserve_flow(json_path, output_file="classified_pipeline_tags.json", threshold=0.6):
    # Step 1: Load normalized merged JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    flow_data = data.get("complete_pipeline_flows", {})
    process_data = data.get("process_data", {})

    # Step 2: Gather all known pipeline tags to detect them
    all_pipeline_tags = set(flow_data.keys())
    print(f"🔍 Found {len(all_pipeline_tags)} pipeline tags (will be categorized as 'pipeline').")

    # Step 3: Prepare lookup dictionaries for process_data
    equipment = process_data.get("Equipment", [])
    instruments = process_data.get("Instrumentation", [])
    handvalves = process_data.get("HandValves", [])

    equipment_tags = {str(e.get("Tag", "")).lower(): e for e in equipment}
    instrument_tags = {str(i.get("Tag", "")).lower(): i for i in instruments}
    handvalve_tags = {str(h.get("Tag", "")).lower(): h for h in handvalves}

    def find_best_match(tag):
        """Find best match and category for a tag (equipment, instrumentation, handvalve, pipeline, or node)."""
        if not isinstance(tag, str) or not tag.strip():
            return {"category": "node", "details": None, "score": 0}

        tag_lower = tag.lower().strip()

        # ✅ Direct match with pipeline tags
        for p_tag in all_pipeline_tags:
            if tag == p_tag:  # exact match to pipeline
                return {"category": "pipeline", "details": None, "score": 1.0}

        # ✅ Fuzzy match check with process data
        best = {"category": "node", "details": None, "score": 0}
        for cat_name, tag_dict in [
            ("equipment", equipment_tags),
            ("instrumentation", instrument_tags),
            ("handvalve", handvalve_tags),
        ]:
            for ref_tag, details in tag_dict.items():
                score = similarity(tag_lower, ref_tag)
                if score > best["score"]:
                    best = {"category": cat_name, "details": details, "score": score}

        # Apply threshold to accept fuzzy match
        if best["score"] >= threshold:
            return best
        return {"category": "node", "details": None, "score": best["score"]}

    # Step 4: Create a deep copy of flow data and enrich it
    classified_flows = {}

    for pipe_tag, pipe_info in flow_data.items():
        # Copy the structure exactly
        new_pipe = json.loads(json.dumps(pipe_info))

        # Enrich 'start' and 'end'
        for key in ["start", "end"]:
            if key in new_pipe and new_pipe[key]:
                tag = new_pipe[key]
                match = find_best_match(tag)
                new_pipe[key] = {
                    "tag": tag,
                    "category": match["category"],
                    "details": match["details"]
                }

        # Enrich 'complete_flow'
        if "complete_flow" in new_pipe and isinstance(new_pipe["complete_flow"], list):
            enriched_flow = []
            for tag in new_pipe["complete_flow"]:
                match = find_best_match(tag)
                enriched_flow.append({
                    "tag": tag,
                    "category": match["category"],
                    "details": match["details"]
                })
            new_pipe["complete_flow"] = enriched_flow

        # Enrich 'all_connections'
        if "all_connections" in new_pipe and isinstance(new_pipe["all_connections"], list):
            enriched_connections = []
            for conn in new_pipe["all_connections"]:
                from_tag = conn.get("from")
                to_tag = conn.get("to")

                from_match = find_best_match(from_tag)
                to_match = find_best_match(to_tag)

                enriched_connections.append({
                    "from": {
                        "tag": from_tag,
                        "category": from_match["category"],
                        "details": from_match["details"]
                    },
                    "to": {
                        "tag": to_tag,
                        "category": to_match["category"],
                        "details": to_match["details"]
                    }
                })
            new_pipe["all_connections"] = enriched_connections

        classified_flows[pipe_tag] = new_pipe

    # Step 5: Combine with process_data and save
    final_output = {
        "complete_pipeline_flows": classified_flows,
        "process_data": process_data
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print(f"✅ Classified tags added → {output_file}")
    print("✅ Flow structure preserved exactly as in normalized_merged_pid.json")
    print("✅ Pipeline tags now correctly categorized as 'pipeline'")
    print("✅ process_data retained in final output")

# Example usage
if __name__ == "__main__":
    classify_tags_preserve_flow("normalized_merged_pid2.json", "classified_pipeline_tags2.json")
