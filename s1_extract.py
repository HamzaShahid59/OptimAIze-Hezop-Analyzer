import sqlite3
import pandas as pd
import json
import os

def extract_dcf_to_files(dcf_path, output_dir="output"):
    # Create output folders
    csv_dir = os.path.join(output_dir, "csv_output")
    json_dir = os.path.join(output_dir, "json_output")
    os.makedirs(csv_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)

    # Connect to the DCF (SQLite) file
    conn = sqlite3.connect(dcf_path)
    cursor = conn.cursor()

    # Fetch all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]

    print(f"✅ Found {len(tables)} tables in {dcf_path}")

    all_data = {}  # To collect everything for JSON

    # Loop through tables
    for table in tables:
        try:
            df = pd.read_sql_query(f"SELECT * FROM '{table}';", conn)
            # Convert bytes to strings if needed
            for col in df.columns:
                if df[col].dtype == object:
                    df[col] = df[col].apply(lambda x: x.decode('utf-8', errors='replace')
                                            if isinstance(x, (bytes, bytearray)) else x)

            # Save each table as CSV
            csv_path = os.path.join(csv_dir, f"{table}.csv")
            df.to_csv(csv_path, index=False)
            print(f"📁 Saved table '{table}' → {csv_path}")

            # Add to combined JSON structure
            all_data[table] = df.to_dict(orient="records")

        except Exception as e:
            print(f"⚠️ Could not read table {table}: {e}")

    conn.close()

    # Save all data to a single JSON file
    json_path = os.path.join(json_dir, "dcf_full_export.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ All CSV files saved in: {csv_dir}")
    print(f"✅ Combined JSON saved as: {json_path}")


# Example usage
if __name__ == "__main__":
    # Change this path to your actual file
    dcf_file = "ProcessPower.dcf"
    extract_dcf_to_files(dcf_file)
