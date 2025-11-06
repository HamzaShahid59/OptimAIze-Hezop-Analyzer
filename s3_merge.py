import sqlite3
import json
import pandas as pd
import os

def merge_pid_core(dcf_path, flow_json_path, output_file="merged_pid_core.json"):
    # Step 1: Load the flow file
    with open(flow_json_path, "r", encoding="utf-8") as f:
        flow_data = json.load(f)
    print(f"✅ Loaded flow data → {len(flow_data)} pipelines")

    # Step 2: Connect to the DCF SQLite database
    conn = sqlite3.connect(dcf_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    # Step 3: Find target tables (case-insensitive)
    target_tables = []
    for name in tables:
        lower_name = name.lower()
        if "equip" in lower_name or "instr" in lower_name or "handvalve" in lower_name:
            target_tables.append(name)

    print(f"🔍 Found {len(target_tables)} relevant tables: {target_tables}")

    # Step 4: Extract data from the three target tables
    extracted_data = {}
    for table in target_tables:
        try:
            df = pd.read_sql_query(f"SELECT * FROM '{table}';", conn)
            # Decode bytes if needed
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].apply(
                        lambda x: x.decode("utf-8", errors="replace")
                        if isinstance(x, (bytes, bytearray))
                        else x
                    )

            # 🟢 Rename 'Area' → 'Details' in Instrumentation table
            if "instr" in table.lower():
                df = df.rename(columns={"Area": "Details"})

            extracted_data[table] = df.to_dict(orient="records")
            print(f"📦 Extracted {len(df)} rows from {table}")
        except Exception as e:
            print(f"⚠️ Could not read {table}: {e}")

    conn.close()

    # Step 5: Build final merged JSON
    merged_data = {
        "complete_pipeline_flows": flow_data,
        "process_data": {
            "Equipment": extracted_data.get("Equipment", []),
            "Instrumentation": extracted_data.get("Instrumentation", []),
            "HandValves": extracted_data.get("HandValves", [])
        }
    }

    # Step 6: Save the merged result
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Final merged JSON saved → {output_file}")
    print(f"✅ Includes: Equipment + Instrumentation (Area→Details) + HandValves")


# Example usage
if __name__ == "__main__":
    dcf_file = "ProcessPower.dcf"  # your DCF file
    flow_json = "complete_pipeline_flows_sequential.json"  # your flow JSON
    merge_pid_core(dcf_file, flow_json)
