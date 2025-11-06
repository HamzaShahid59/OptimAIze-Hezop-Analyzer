import streamlit as st
import json
import re
import os
import openai
from difflib import SequenceMatcher
import random

# ==========================
# Load JSON Data
# ==========================
with open("classified_pipeline_tags2.json", "r", encoding="utf-8") as f:
    DATA = json.load(f)

PIPELINES = DATA.get("complete_pipeline_flows", {})
PROCESS_DATA = DATA.get("process_data", {})

# ==========================
# Helper Functions
# ==========================
def normalize_tag(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', tag).lower()

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def find_best_tag_matches(query, data_dict, threshold=0.6):
    results = []
    q = normalize_tag(query)
    for item in data_dict:
        tag = normalize_tag(item.get("Tag", ""))
        if similarity(q, tag) >= threshold:
            results.append(item)
    return results

def find_pipeline_matches(query, threshold=0.6):
    q = normalize_tag(query)
    matches = {}
    for pipe_tag, pipe_info in PIPELINES.items():
        if similarity(q, normalize_tag(pipe_tag)) >= threshold:
            matches[pipe_tag] = pipe_info
    return matches

def build_local_context(query):
    context = {"equipment": [], "instrumentation": [], "handvalves": [], "pipelines": {}}
    q = query.lower()

    # General category queries
    if any(word in q for word in ["pipeline", "line", "flow path", "pipe"]):
        context["pipelines"] = PIPELINES
        return context
    elif any(word in q for word in ["equipment", "pump", "tank", "vessel", "reactor"]):
        context["equipment"] = PROCESS_DATA.get("Equipment", [])
        return context
    elif any(word in q for word in ["instrument", "valve", "controller", "sensor"]):
        context["instrumentation"] = PROCESS_DATA.get("Instrumentation", [])
        context["handvalves"] = PROCESS_DATA.get("HandValves", [])
        return context

    # Specific tag searches
    context["equipment"] = find_best_tag_matches(query, PROCESS_DATA.get("Equipment", []))
    context["instrumentation"] = find_best_tag_matches(query, PROCESS_DATA.get("Instrumentation", []))
    context["handvalves"] = find_best_tag_matches(query, PROCESS_DATA.get("HandValves", []))
    context["pipelines"] = find_pipeline_matches(query)
    return context

def summarize_context(context):
    lines = []
    if context["equipment"]:
        lines.append("Matched Equipment:")
        for e in context["equipment"]:
            lines.append(json.dumps(e, indent=2))
    if context["instrumentation"]:
        lines.append("Matched Instrumentation:")
        for i in context["instrumentation"]:
            lines.append(json.dumps(i, indent=2))
    if context["handvalves"]:
        lines.append("Matched Hand Valves:")
        for h in context["handvalves"]:
            lines.append(json.dumps(h, indent=2))
    if context["pipelines"]:
        lines.append("Matched Pipelines:")
        for tag, info in context["pipelines"].items():
            lines.append(f"{tag}: {json.dumps(info, indent=2)}")
    if not lines:
        return "No matching data found in plant model."
    return "\n".join(lines)

# ==========================
# Few-Shot Examples from Real Data
# ==========================
def build_fewshot_examples():
    examples = []
    eq_list = PROCESS_DATA.get("Equipment", [])
    inst_list = PROCESS_DATA.get("Instrumentation", [])
    if eq_list:
        eq = random.choice(eq_list)
        examples.append({
            "role": "user",
            "content": f"What are the specifications of equipment {eq.get('Tag','?')}?"
        })
        examples.append({
            "role": "assistant",
            "content": f"Equipment {eq.get('Tag','?')} has specifications as follows: {eq.get('EquipmentSpec','Not available')}."
        })
    if inst_list:
        inst = random.choice(inst_list)
        examples.append({
            "role": "user",
            "content": f"What is the operational state of instrument {inst.get('Tag','?')}?"
        })
        examples.append({
            "role": "assistant",
            "content": f"Instrument {inst.get('Tag','?')} is currently '{inst.get('Area','unknown')}'."
        })
    if PIPELINES:
        tag = random.choice(list(PIPELINES.keys()))
        pipe = PIPELINES[tag]
        start = pipe.get("start", {}).get("tag", "unknown")
        end = pipe.get("end", {}).get("tag", "unknown")
        examples.append({
            "role": "user",
            "content": f"What does pipeline {tag} connect?"
        })
        examples.append({
            "role": "assistant",
            "content": f"Pipeline {tag} connects from {start} to {end}."
        })
    return examples

# ==========================
# GPT Setup - FIXED FOR OPENAI 1.x
# ==========================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("❌ No API key found. Please set OPENAI_API_KEY in environment.")
    st.stop()

# Initialize OpenAI client - FIXED SYNTAX
# Configure openai with the API key (compatible with openai versions that export a module)
openai.api_key = api_key

# ==========================
# Streamlit UI
# ==========================
st.set_page_config(page_title="P&ID Analysis Chatbot", layout="wide")
st.title("🧠 P&ID Analysis Chatbot")

few_shots = build_fewshot_examples()

# ==========================
# Memory Initialization
# ==========================
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content":
         "You are a process engineer expert in P&ID and HAZOP interpretation. "
         "Answer questions using provided JSON context. Maintain conversational memory. "
         "If the user says 'it', 'this pipeline', or 'that instrument', infer from the previous topic."}
    ] + few_shots

if "last_reference" not in st.session_state:
    st.session_state.last_reference = None  # track last tag discussed

# Display previous conversation (excluding few-shots)
for msg in st.session_state.messages:
    if msg["role"] != "system" and msg not in few_shots:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ==========================
# Chat Input
# ==========================
user_input = st.chat_input("Ask about any equipment, pipeline, or instrument...")
if user_input:
    # Update reference context if user refers to 'it' etc.
    if any(word in user_input.lower() for word in ["it", "this", "that", "its"]):
        if st.session_state.last_reference:
            user_input = f"{user_input} (Refers to {st.session_state.last_reference})"

    st.chat_message("user").markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    # Build local context
    context = build_local_context(user_input)
    context_text = summarize_context(context)

    # Track last referenced tag
    for cat in ["equipment", "instrumentation", "handvalves"]:
        if context[cat]:
            st.session_state.last_reference = context[cat][0].get("Tag", None)
    if context["pipelines"]:
        st.session_state.last_reference = list(context["pipelines"].keys())[0]

    # Combine messages
    messages = st.session_state.messages + [
        {"role": "system", "content": f"Relevant plant data:\n{context_text}"}
    ]

    try:
        # Use the classic ChatCompletion API which is compatible with many openai versions
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.25,
        )

        # Extract reply text robustly for different response shapes
        if isinstance(response, dict):
            choice = response.get("choices", [{}])[0]
            # Newer responses may put content under choice['message']['content']
            reply = (
                choice.get("message", {}).get("content")
                or choice.get("text")
                or str(choice)
            )
        else:
            # Fallback to string representation
            reply = str(response)
    except Exception as e:
        reply = f"⚠️ Error calling GPT: {str(e)}"

    # Display assistant reply
    st.chat_message("assistant").markdown(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})