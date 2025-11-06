import streamlit as st
import json
import re
import os
from difflib import SequenceMatcher
import random
from dotenv import load_dotenv
from openai import OpenAI  # ✅ modern client for openai>=1.0.0

# ==========================
# Streamlit Page Config
# ==========================
st.set_page_config(page_title="🧠 P&ID Analysis Chatbot", layout="wide")
st.title("🧠 P&ID Analysis Chatbot")

# ==========================
# Load environment variables
# ==========================
load_dotenv()
api_key = os.getenv("OPEN_AI_KEY")

if not api_key:
    st.error("❌ No API key found. Please set OPEN_AI_KEY in your .env file.")
    st.stop()

# Initialize client
client = OpenAI(api_key=api_key)

# ==========================
# Load JSON Data
# ==========================
try:
    with open("classified_pipeline_tags2.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
except FileNotFoundError:
    st.error("❌ Missing 'classified_pipeline_tags2.json' file.")
    st.stop()
except json.JSONDecodeError:
    st.error("❌ Invalid JSON in 'classified_pipeline_tags2.json'. Please check format.")
    st.stop()

PIPELINES = DATA.get("complete_pipeline_flows", {})
PROCESS_DATA = DATA.get("process_data", {})

# ==========================
# Helper Functions
# ==========================
def normalize_tag(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    return re.sub(r"[^a-zA-Z0-9]", "", tag).lower()

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def find_best_tag_matches(query, data_list, threshold=0.6):
    """Finds equipment/instrument/valve tags matching query."""
    results = []
    if not data_list:
        return results

    q_raw = query.lower()
    q_norm = normalize_tag(query)

    for item in data_list:
        tag = item.get("Tag", "")
        tag_lower = tag.lower()
        tag_norm = normalize_tag(tag)

        if tag_lower and tag_lower in q_raw:
            results.append(item)
        elif tag_norm and similarity(q_norm, tag_norm) >= threshold:
            results.append(item)

    return results

def find_pipeline_matches(query, threshold=0.6):
    """Find pipeline matches by tag or fuzzy match."""
    matches = {}
    q_raw = query.lower()
    q_norm = normalize_tag(query)

    for pipe_tag, pipe_info in PIPELINES.items():
        tag_lower = pipe_tag.lower()
        tag_norm = normalize_tag(pipe_tag)
        if tag_lower in q_raw or similarity(q_norm, tag_norm) >= threshold:
            matches[pipe_tag] = pipe_info
    return matches

def extract_all_equipment_like_objects():
    """Extract all equipment (including start/end from pipelines)."""
    equipment_list = PROCESS_DATA.get("Equipment", []).copy()
    for pipe_tag, pipe in PIPELINES.items():
        for end in ["start", "end"]:
            node = pipe.get(end, {})
            if node.get("category") == "equipment" and node.get("details"):
                equipment_list.append(node["details"])
    return equipment_list

def build_local_context(query):
    """Build a detailed context from JSON for the model."""
    context = {"equipment": [], "instrumentation": [], "handvalves": [], "pipelines": {}}
    q = query.lower()
    all_equipment = extract_all_equipment_like_objects()

    context["equipment"] = find_best_tag_matches(query, all_equipment)
    context["instrumentation"] = find_best_tag_matches(query, PROCESS_DATA.get("Instrumentation", []))
    context["handvalves"] = find_best_tag_matches(query, PROCESS_DATA.get("HandValves", []))
    context["pipelines"] = find_pipeline_matches(query)

    # Pull start/end equipment for matched pipelines
    for pipe_info in context["pipelines"].values():
        for end in ["start", "end"]:
            node = pipe_info.get(end, {})
            if node.get("details"):
                context["equipment"].append(node["details"])

    return context

def summarize_context(context):
    """Format local context into readable text for GPT."""
    lines = []

    if context["equipment"]:
        lines.append("Equipment found:")
        for e in context["equipment"]:
            lines.append(
                f"- Tag: {e.get('Tag')} | Type: {e.get('Type')} | "
                f"Spec: {e.get('EquipmentSpec')} | Area: {e.get('Area')}"
            )

    if context["instrumentation"]:
        lines.append("\nInstrumentation found:")
        for i in context["instrumentation"]:
            lines.append(f"- Tag: {i.get('Tag')} | Type: {i.get('Type')} | Details: {i.get('Details')}")

    if context["pipelines"]:
        lines.append("\nPipelines found:")
        for tag, p in context["pipelines"].items():
            start = (p.get("start", {}).get("details") or {}).get("Tag", p.get("start", {}).get("tag"))
            end = (p.get("end", {}).get("details") or {}).get("Tag", p.get("end", {}).get("tag"))
            lines.append(f"- {tag} connects {start} → {end}")

    return "\n".join(lines) if lines else "No relevant data found."

# ==========================
# Prompt Configuration
# ==========================
def build_fewshot_examples():
    """Few-shots showing model how to extract temperature/capacity from EquipmentSpec."""
    return [
        {
            "role": "user",
            "content": "What is the temperature range of equipment b440?",
        },
        {
            "role": "assistant",
            "content": (
                "According to the JSON context, equipment b440 has "
                "EquipmentSpec 'Tank DMPSA 1 m^3 Temp = 50-60°C'. "
                "Therefore, its temperature range is 50–60°C."
            ),
        },
        {
            "role": "user",
            "content": "What is the capacity of equipment b440?",
        },
        {
            "role": "assistant",
            "content": (
                "From the EquipmentSpec of b440 ('Tank DMPSA 1 m^3 Temp = 50-60°C'), "
                "the tank capacity is 1 m³."
            ),
        },
        {
            "role": "user",
            "content": "If data is missing, what should you say?",
        },
        {
            "role": "assistant",
            "content": (
                "If a tag truly does not exist in the JSON context, say: "
                "'That information does not exist in the provided JSON data.'"
            ),
        },
    ]

# ==========================
# Session State Initialization
# ==========================
if "system_message" not in st.session_state:
    st.session_state.system_message = {
        "role": "system",
        "content": (
            "You are a process engineer assistant with full access to a JSON-based P&ID model.\n"
            "You must answer using only the 'Relevant plant data' provided to you.\n"
            "When EquipmentSpec includes values like temperature or capacity, extract them explicitly.\n"
            "Never say 'information not available' if it appears anywhere in the JSON context.\n"
            "If it’s truly missing, respond with: 'That information does not exist in the provided JSON data.'"
        ),
    }

if "few_shots" not in st.session_state:
    st.session_state.few_shots = build_fewshot_examples()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "last_reference" not in st.session_state:
    st.session_state.last_reference = None

# ==========================
# Display chat history
# ==========================
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ==========================
# User Input
# ==========================
user_input = st.chat_input("Ask about any equipment, pipeline, or instrument...")

if user_input:
    # Handle pronoun references
    if any(word in user_input.lower() for word in ["it", "this", "that", "its"]):
        if st.session_state.last_reference:
            user_input = f"{user_input} (Refers to {st.session_state.last_reference})"

    st.chat_message("user").markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    # Build local context
    context = build_local_context(user_input)
    context_text = summarize_context(context)

    # Update last reference
    if context["equipment"]:
        st.session_state.last_reference = context["equipment"][0].get("Tag")
    elif context["pipelines"]:
        st.session_state.last_reference = list(context["pipelines"].keys())[0]

    # Build final prompt
    messages = (
        [st.session_state.system_message]
        + st.session_state.few_shots
        + st.session_state.chat_history
        + [{"role": "system", "content": f"Relevant plant data:\n{context_text}"}]
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.25,
        )
        reply = response.choices[0].message.content
    except Exception as e:
        reply = f"⚠️ GPT error: {str(e)}"

    st.chat_message("assistant").markdown(reply)
    st.session_state.chat_history.append({"role": "assistant", "content": reply})
