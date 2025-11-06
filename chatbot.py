import sqlite3
import json
import os
import pandas as pd

def identify_tag_properties(dcf_path, flow_json_path, output_dir="output_analysis"):
    os.makedirs(output_dir, exist_ok=True)

    # Load the flow JSON
    with open(flow_json_path, "r", encoding="utf-8") as f:
        flow_data = json.load(f)

    # Connect to DCF file
    conn = sqlite3.connect(dcf_path)
    cursor = conn.cursor()

    # Get all tables except pipelines
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    all_tables = [t[0] for t in cursor.fetchall()]
    non_pipeline_tables = [t for t in all_tables if "pipeline" not in t.lower()]

    print(f"✅ Found {len(non_pipeline_tables)} non-pipeline tables.")
    print(f"🔍 Checking tags against these tables:\n{non_pipeline_tables}\n")

    # Load each table as a DataFrame
    table_data = {}
    for table in non_pipeline_tables:
        try:
            df = pd.read_sql_query(f"SELECT * FROM '{table}';", conn)
            # Decode bytes if needed
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8', errors='replace')
                                            if isinstance(x, (bytes, bytearray)) else x)
            table_data[table] = df
        except Exception as e:
            print(f"⚠️ Skipping table {table}: {e}")

    conn.close()

    # Helper to find a tag across tables
    def find_tag_info(tag):
        tag_str = str(tag).strip().lower()
        for table, df in table_data.items():
            # Check in 'Tag' or similar columns
            for col in df.columns:
                if "tag" in col.lower():
                    matches = df[df[col].astype(str).str.lower() == tag_str]
                    if not matches.empty:
                        record = matches.iloc[0].to_dict()
                        # Categorize
                        if "equip" in table.lower():
                            cat = "equipment"
                        elif "instr" in table.lower():
                            cat = "instrumentation"
                        elif "valve" in table.lower():
                            cat = "handvalve"
                        else:
                            cat = "node"
                        return {"category": cat, "table": table, "properties": record}
        # Not found
        return {"category": "node", "table": None, "properties": None}

    # Iterate through each flow and verify tags
    verification_results = {}

    for pipeline_tag, details in flow_data.items():
        pipeline_info = {"pipeline_tag": pipeline_tag, "connections": []}

        all_connections = details.get("all_connections", [])
        for conn_item in all_connections:
            from_tag = conn_item.get("from")
            to_tag = conn_item.get("to")

            from_info = find_tag_info(from_tag)
            to_info = find_tag_info(to_tag)

            pipeline_info["connections"].append({
                "from": from_tag,
                "from_category": from_info["category"],
                "from_table": from_info["table"],
                "from_properties": from_info["properties"],
                "to": to_tag,
                "to_category": to_info["category"],
                "to_table": to_info["table"],
                "to_properties": to_info["properties"],
            })

        verification_results[pipeline_tag] = pipeline_info

    # Save results
    json_out = os.path.join(output_dir, "pipeline_tag_verification.json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(verification_results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Verification completed. Output saved to: {json_out}")
    print(f"✅ Total pipelines processed: {len(verification_results)}")

# Example usage
if __name__ == "__main__":
    dcf_file = "DMPP/ProcessPower.dcf"  # your DCF file
    flow_json = "complete_pipeline_flows_sequential.json"  # your JSON flow file
    identify_tag_properties(dcf_file, flow_json)
