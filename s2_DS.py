import pandas as pd
import json
import re

def extract_complete_pipeline_flows(csv_file_path):
    # Read the pipeline CSV file
    df_pipelines = pd.read_csv(csv_file_path)
    
    print("🔄 Reading pipeline data...")
    print(f"Total rows in CSV: {len(df_pipelines)}")
    print(f"Unique pipeline tags: {len(df_pipelines['Tag'].unique())}")
    
    # Clean the data
    df_pipelines['From'] = df_pipelines['From'].astype(str).str.strip()
    df_pipelines['To'] = df_pipelines['To'].astype(str).str.strip()
    df_pipelines['Tag'] = df_pipelines['Tag'].astype(str).str.strip()
    
    # Remove problematic characters
    df_pipelines['From'] = df_pipelines['From'].apply(clean_text)
    df_pipelines['To'] = df_pipelines['To'].apply(clean_text)
    
    # Dictionary to store all pipeline flows
    pipeline_flows = {}
    
    # Process each pipeline tag
    for tag in df_pipelines['Tag'].unique():
        if pd.isna(tag) or not tag or tag == 'nan':
            continue
            
        print(f"\n🔍 Processing pipeline: {tag}")
        
        # Get ALL rows for this pipeline tag
        tag_data = df_pipelines[df_pipelines['Tag'] == tag]
        
        # Extract ALL connections in order
        connections = []
        for _, row in tag_data.iterrows():
            from_node = str(row['From']).strip()
            to_node = str(row['To']).strip()
            
            # Handle missing "To" values by using "RELEASE"
            if from_node and from_node != 'nan':
                if not to_node or to_node == 'nan':
                    to_node = 'RELEASE'
                connections.append({
                    'from': from_node,
                    'to': to_node
                })
        
        print(f"   Found {len(connections)} connections")
        
        if connections:
            # Build flow by following the actual sequence
            complete_flow = build_flow_by_following_sequence(connections)
            
            pipeline_flows[tag] = {
                'pipeline_tag': tag,
                'total_connections': len(connections),
                'complete_flow': complete_flow,
                'start': complete_flow[0] if complete_flow else None,
                'end': complete_flow[-1] if complete_flow else None,
                'all_raw_connections': connections
            }
            
            print(f"   ✅ Complete flow: {len(complete_flow)} nodes")
            print(f"   Start: {complete_flow[0] if complete_flow else 'None'}")
            print(f"   End: {complete_flow[-1] if complete_flow else 'None'}")
            print(f"   Flow: {' → '.join(complete_flow)}")
        else:
            print(f"   ❌ No valid connections found")
    
    return pipeline_flows

def build_flow_by_following_sequence(connections):
    """Build flow by following the actual connection sequence"""
    if not connections:
        return []
    
    # For single connection pipelines
    if len(connections) == 1:
        return [connections[0]['from'], connections[0]['to']]
    
    # Start with the first connection
    flow = [connections[0]['from'], connections[0]['to']]
    used_connections = [0]  # Track which connections we've used
    
    # Continue building the flow until all connections are used
    while len(used_connections) < len(connections):
        found_extension = False
        
        # Try to extend from the end
        last_node = flow[-1]
        for i, conn in enumerate(connections):
            if i not in used_connections:
                if conn['from'] == last_node:
                    flow.append(conn['to'])
                    used_connections.append(i)
                    found_extension = True
                    break
                elif conn['to'] == last_node:
                    flow.append(conn['from'])
                    used_connections.append(i)
                    found_extension = True
                    break
        
        # If couldn't extend from end, try to prepend from start
        if not found_extension:
            first_node = flow[0]
            for i, conn in enumerate(connections):
                if i not in used_connections:
                    if conn['to'] == first_node:
                        flow.insert(0, conn['from'])
                        used_connections.append(i)
                        found_extension = True
                        break
                    elif conn['from'] == first_node:
                        flow.insert(0, conn['to'])
                        used_connections.append(i)
                        found_extension = True
                        break
        
        # If still no extension found, add remaining connections as disconnected segments
        if not found_extension:
            for i, conn in enumerate(connections):
                if i not in used_connections:
                    # Add this disconnected connection
                    if conn['from'] not in flow:
                        flow.append(conn['from'])
                    if conn['to'] not in flow:
                        flow.append(conn['to'])
                    used_connections.append(i)
            break
    
    return flow

def clean_text(text):
    """Clean text from encoding issues"""
    if pd.isna(text) or text == 'nan':
        return ""
    
    text = str(text)
    # Remove encoding artifacts but keep the structure
    text = re.sub(r'Âḟ', ' ', text)
    text = re.sub(r'Â', ' ', text)
    text = re.sub(r'Ḟ', ' ', text)
    text = re.sub(r'±', ' ', text)
    text = re.sub(r'°', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('\n', ' ').replace('\r', ' ')
    
    return text.strip()

def save_flows_to_json(pipeline_flows, output_file):
    """Save the pipeline flows to JSON file"""
    json_output = {}
    
    for pipeline_tag, data in pipeline_flows.items():
        json_output[pipeline_tag] = {
            "pipeline_tag": pipeline_tag,
            "start": data['start'],
            "end": data['end'],
            "complete_flow": data['complete_flow'],
            "total_connections": data['total_connections'],
            "flow_length": len(data['complete_flow']),
            "all_connections": data['all_raw_connections']
        }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Pipeline flows saved to: {output_file}")
    return json_output

# File path
csv_file_path = "output/csv_output/PipeLines.csv"

print("🚀 EXTRACTING COMPLETE PIPELINE FLOWS WITH SEQUENTIAL FLOW")
print("=" * 60)

try:
    # Step 1: Extract complete flows
    pipeline_flows = extract_complete_pipeline_flows(csv_file_path)
    
    # Step 2: Save to JSON
    output_file = "complete_pipeline_flows_sequential.json"
    json_result = save_flows_to_json(pipeline_flows, output_file)
    
    # Step 3: Show summary
    print(f"\n📊 EXTRACTION SUMMARY:")
    print("=" * 50)
    print(f"Total pipelines processed: {len(pipeline_flows)}")
    
    total_connections = sum(flow['total_connections'] for flow in pipeline_flows.values())
    total_nodes = sum(len(flow['complete_flow']) for flow in pipeline_flows.values())
    
    print(f"Total connections: {total_connections}")
    print(f"Total nodes in all flows: {total_nodes}")
    
    # Show pipeline statistics
    single_connection_pipelines = [tag for tag, data in pipeline_flows.items() if data['total_connections'] == 1]
    multi_connection_pipelines = [tag for tag, data in pipeline_flows.items() if data['total_connections'] > 1]
    
    print(f"\n📈 PIPELINE STATISTICS:")
    print(f"Single-connection pipelines: {len(single_connection_pipelines)}")
    print(f"Multi-connection pipelines: {len(multi_connection_pipelines)}")
    
    # Show pipelines with RELEASE endpoints
    release_pipelines = [tag for tag, data in pipeline_flows.items() if 'RELEASE' in data['complete_flow']]
    print(f"Pipelines with RELEASE endpoints: {len(release_pipelines)}")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()