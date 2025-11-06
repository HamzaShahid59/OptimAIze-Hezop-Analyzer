import streamlit as st
import json
import re
import os
from difflib import SequenceMatcher
import random
from dotenv import load_dotenv
from openai import OpenAI  # new-style OpenAI client

# ==========================
# Streamlit Page Config
# ==========================
st.set_page_config(page_title="P&ID Analysis Chatbot", layout="wide")
st.title("🧠 P&ID Analysis Chatbot")

# ==========================
# Load environment variables from .env
# ==========================
load_dotenv()

# Read key from .env / environment as OPEN_AI_KEY
api_key = os.getenv("OPEN_AI_KEY")
if not api_key:
    st.error("❌ No API key found. Please set OPEN_AI_KEY in your .env file.")
    st.stop()

# Initialize OpenAI client (for openai>=1.0.0, including 2.7.x)
client = OpenAI(api_key=api_key)

# ==========================
# Load JSON Data
# ==========================
try:
    with open("classified_pipeline_tags2.json", "r", encoding="utf-8") as f:
        DATA = json.load(f)
except FileNotFoundError:
    st.error("❌ Data file 'classified_pipeline_tags2.json' not found in the app directory.")
    st.stop()
except json.JSONDecodeError:
    st.error(
        "❌ 'classified_pipeline_tags2.json' is not valid JSON. "
        "Make sure it is generated correctly and committed."
    )
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
    """
    Improved matcher:
    - First do simple substring match of Tag in the raw query.
    - Fallback to fuzzy similarity on normalized strings.
    """
    results = []
    if not data_list:
        return results

    q_raw = query.lower()
    q_norm = normalize_tag(query)

    for item in data_list:
        tag = item.get("Tag", "")
        tag_lower = tag.lower()
        tag_norm = normalize_tag(tag)

        # Direct substring match on raw text (strong signal)
        if tag_lower and tag_lower in q_raw:
            results.append(item)
            continue

        # Fuzzy match as backup
        if tag_norm and similarity(q_norm, tag_norm) >= threshold:
            results.append(item)

    return results


def find_pipeline_matches(query, threshold=0.6):
    """
    Improved pipeline matcher:
    - Direct substring match of pipeline tag in query.
    - Fallback to fuzzy similarity.
    """
    q_raw = query.lower()
    q_norm = normalize_tag(query)
    matches = {}

    for pipe_tag, pipe_info in PIPELINES.items():
        tag_lower = pipe_tag.lower()
        tag_norm = normalize_tag(pipe_tag)

        if tag_lower in q_raw:
            matches[pipe_tag] = pipe_info
            continue

        if similarity(q_norm, tag_norm) >= threshold:
            matches[pipe_tag] = pipe_info

    return matches


def build_local_context(query):
    """
    Build a local context tailored to the query:
    - Matches equipment/instrumentation/handvalves by tag or similarity.
    - Matches pipelines by tag or similarity.
    - When a pipeline is matched, also pulls its start/end equipment details
      into the equipment context so things like temperature/capacity of B440
      are available.
    """
    context = {"equipment": [], "instrumentation": [], "handvalves": [], "pipelines": {}}
    q = query.lower()

    # General category queries
    if any(word in q for word in ["pipeline", "line", "flow path", "pipe"]):
        context["pipelines"] = PIPELINES
    elif any(word in q for word in ["equipment", "pump", "tank", "vessel", "reactor"]):
        context["equipment"] = PROCESS_DATA.get("Equipment", [])
    elif any(word in q for word in ["instrument", "valve", "controller", "sensor"]):
        context["instrumentation"] = PROCESS_DATA.get("Instrumentation", [])
        context["handvalves"] = PROCESS_DATA.get("HandValves", [])
    else:
        # Specific tag / free-text search
        context["equipment"] = find_best_tag_matches(query, PROCESS_DATA.get("Equipment", []))
        context["instrumentation"] = find_best_tag_matches(
            query, PROCESS_DATA.get("Instrumentation", [])
        )
        context["handvalves"] = find_best_tag_matches(
            query, PROCESS_DATA.get("HandValves", [])
        )
        context["pipelines"] = find_pipeline_matches(query)

    # If pipelines were matched, pull their start/end equipment into equipment context
    if context["pipelines"]:
        existing_tags = {e.get("Tag") for e in context["equipment"]}
        for pipe_info in context["pipelines"].values():
            for end_key in ["start", "end"]:
                node = pipe_info.get(end_key, {})
                if node.get("category") == "equipment":
                    det = node.get("details") or {}
                    tag = det.get("Tag")
                    if det and tag and tag not in existing_tags:
                        context["equipment"].append(det)
                        existing_tags.add(tag)

    return context


def summarize_context(context):
    """
    Turn the local context into a compact, very-readable text
    so the model can easily see specs like temperature and capacity.
    """
    lines = []

    if context["equipment"]:
        lines.append("Equipment:")
        for e in context["equipment"]:
            tag = e.get("Tag", "")
            typ = e.get("Type", "")
            spec = e.get("EquipmentSpec", "")
            lines.append(f"- {tag} (type {typ}): spec = {spec}")

    if context["instrumentation"]:
        lines.append("Instrumentation:")
        for i in context["instrumentation"]:
            tag = i.get("Tag", "")
            typ = i.get("Type", "")
            details = i.get("Details", "")
            lines.append(f"- {tag} (type {typ}): details = {details}")

    if context["handvalves"]:
        lines.append("Hand valves:")
        for h in context["handvalves"]:
            tag = h.get("Tag", "")
            code = h.get("Code", "")
            normally = h.get("Normally", "")
            lines.append(f"- {tag} (code {code}, normally {normally})")

    if context["pipelines"]:
        lines.append("Pipelines:")
        for tag, info in context["pipelines"].items():
            start = info.get("start", {})
            end = info.get("end", {})
            s_tag = (start.get("details") or {}).get("Tag") or start.get("tag", "unknown")
            e_tag = (end.get("details") or {}).get("Tag") or end.get("tag", "unknown")
            lines.append(f"- {tag}: from {s_tag} to {e_tag}")

    if not lines:
        return "No matching data found in plant model."

    return "\n".join(lines)

# ==========================
# Few-Shot Examples (STATIC)
# Used only for the model, not shown in UI
# ==========================
def build_fewshot_examples():
    """
    Static few-shots that demonstrate how to read EquipmentSpec
    and answer about temperature / capacity from the JSON context.
    """
    return [
        {
            "role": "user",
            "content": "What is the temperature range of equipment b440?",
        },
        {
            "role": "assistant",
            "content": (
                "According to the JSON context, equipment b440 has "
                'EquipmentSpec "Tank DMPSA 1 m^3 Temp = 50-60°C". '
                "So the temperature range is 50–60°C."
            ),
        },
        {
            "role": "user",
            "content": "What is the capacity of equipment b440?",
        },
        {
            "role": "assistant",
            "content": (
                "From the same EquipmentSpec for b440, the tank capacity is 1 m^3."
            ),
        },
        {
            "role": "user",
            "content": "If the information is not in the JSON, what should you say?",
        },
        {
            "role": "assistant",
            "content": (
                "If the requested detail is not present anywhere in the provided JSON "
                "context, I should clearly say that this specific information is not "
                "available in the data."
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
            "You are a process engineer expert in P&ID and HAZOP interpretation. "
            "You answer ONLY using the JSON plant data that is provided to you in the "
            "'Relevant plant data' system message.\n\n"
            "- Carefully read EquipmentSpec and other fields for matching tags.\n"
            "- For questions about temperature, capacity, volume, or operating range, "
            "extract these values directly from EquipmentSpec.\n"
            "- Do NOT say that information is not available if it actually appears "
            "anywhere in the JSON context.\n"
            "- If you genuinely cannot find the information in the JSON, then say "
            "\"this information is not available in the provided data.\""
        ),
    }

if "few_shots" not in st.session_state:
    st.session_state.few_shots = build_fewshot_examples()

# chat_history: ONLY real user & assistant messages that should be displayed
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "last_reference" not in st.session_state:
    st.session_state.last_reference = None  # track last tag discussed

# ==========================
# Display previous conversation
# (only user + assistant messages, no system, no few-shots)
# ==========================
for msg in st.session_state.chat_history:
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

    # Show user message in UI and store in chat_history
    st.chat_message("user").markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    # Build local context
    context = build_local_context(user_input)
    context_text = summarize_context(context)

    # Track last referenced tag (prefer equipment tag)
    if context["equipment"]:
        st.session_state.last_reference = context["equipment"][0].get("Tag", None)
    elif context["pipelines"]:
        st.session_state.last_reference = list(context["pipelines"].keys())[0]

    # ==========================
    # Prepare messages for the model
    #   system + few_shots + full chat_history + extra system context
    # ==========================
    messages = (
        [st.session_state.system_message]
        + st.session_state.few_shots
        + st.session_state.chat_history
        + [
            {
                "role": "system",
                "content": f"Relevant plant data:\n{context_text}",
            }
        ]
    )

    try:
        # Call OpenAI Chat Completions API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.25,
        )
        reply = response.choices[0].message.content
    except Exception as e:
        reply = f"⚠️ Error calling GPT: {str(e)}"

    # Show assistant reply in UI and store in chat_history
    st.chat_message("assistant").markdown(reply)
    st.session_state.chat_history.append({"role": "assistant", "content": reply})
