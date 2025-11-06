import streamlit as st
import json
import re
import os
from difflib import SequenceMatcher
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
    st.error("❌ 'classified_pipeline_tags2.json' not found in the app directory.")
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
    Pipeline matcher by pipeline tag name:
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


# ==========================
# Tag → Pipelines Reverse Index
# ==========================
TAG_TO_PIPELINES = {}


def build_tag_index():
    """
    Build a reverse index from normalized tag -> set of pipeline IDs
    for anything that has a tag (equipment, instrumentation, handvalves, nodes)
    inside pipeline complete_flows.
    """
    index = {}
    for pipe_tag, pipe_info in PIPELINES.items():
        for step in pipe_info.get("complete_flow", []):
            step_tag = step.get("tag")
            details = step.get("details") or {}
            detail_tag = details.get("Tag")

            for t in {step_tag, detail_tag}:
                if not t:
                    continue
                norm = normalize_tag(t)
                index.setdefault(norm, set()).add(pipe_tag)

    return index


TAG_TO_PIPELINES = build_tag_index()


def find_pipelines_for_tag(tag_query: str, threshold: float = 0.7):
    """
    Given a tag-like query (e.g. 'hvmkh441' or 'staalname'),
    return all pipelines that contain that tag anywhere in their flow.
    """
    results = {}
    if not tag_query:
        return results

    q_norm = normalize_tag(tag_query)
    if not q_norm:
        return results

    # 1) direct hit
    direct = TAG_TO_PIPELINES.get(q_norm, set())
    for p_tag in direct:
        if p_tag in PIPELINES:
            results[p_tag] = PIPELINES[p_tag]

    # 2) fuzzy / partial hit
    for t_norm, pipe_ids in TAG_TO_PIPELINES.items():
        if t_norm in q_norm or q_norm in t_norm or similarity(q_norm, t_norm) >= threshold:
            for p_tag in pipe_ids:
                if p_tag in PIPELINES:
                    results[p_tag] = PIPELINES[p_tag]

    return results


def build_local_context(query):
    """
    Build a local context tailored to the query:
    - Matches equipment/instrumentation/handvalves by tag or similarity.
    - Matches pipelines either by pipeline tag or because they contain a
      referenced equipment / instrument / node tag.
    - When a pipeline is matched, also pulls its start/end equipment details
      into the equipment context.
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
        context["equipment"] = find_best_tag_matches(
            query, PROCESS_DATA.get("Equipment", [])
        )
        context["instrumentation"] = find_best_tag_matches(
            query, PROCESS_DATA.get("Instrumentation", [])
        )
        context["handvalves"] = find_best_tag_matches(
            query, PROCESS_DATA.get("HandValves", [])
        )
        # Match by pipeline tag
        context["pipelines"] = find_pipeline_matches(query)

    # Also search pipelines that contain the mentioned tags (incl. nodes like 'staalname')
    extra_pipes = {}

    # 1) try using the raw user query as a tag-like string
    extra_pipes.update(find_pipelines_for_tag(query))

    # 2) try using any matched equipment / instrumentation / handvalve tags
    for section in ["equipment", "instrumentation", "handvalves"]:
        for item in context[section]:
            t = item.get("Tag", "")
            extra_pipes.update(find_pipelines_for_tag(t))

    # Merge explicit matches + extra pipes
    if context["pipelines"]:
        context["pipelines"].update(extra_pipes)
    else:
        context["pipelines"] = extra_pipes

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
    so the model can easily see specs like temperature and capacity,
    as well as which tags sit on which pipelines and key nodes.
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
            # Different JSONs may use Code or ValveCode, try both
            code = h.get("Code", h.get("ValveCode", ""))
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

            # Highlight nodes and important tags on this pipeline
            flow = info.get("complete_flow", [])
            for step in flow:
                if step.get("category") == "node":
                    node_tag = step.get("tag", "")
                    if node_tag:
                        lines.append(f"  • node '{node_tag}' is present in pipeline {tag}")
                elif step.get("category") == "instrumentation":
                    inst_details = step.get("details") or {}
                    inst_tag = inst_details.get("Tag") or step.get("tag", "")
                    if inst_tag:
                        lines.append(f"  • instrumentation '{inst_tag}' is on pipeline {tag}")
                elif step.get("category") == "handvalve":
                    hv_details = step.get("details") or {}
                    hv_tag = hv_details.get("Tag") or step.get("tag", "")
                    if hv_tag:
                        lines.append(f"  • handvalve '{hv_tag}' is on pipeline {tag}")

    if not lines:
        return "No matching data found in plant model."

    return "\n".join(lines)


# ==========================
# Session State Initialization (MEMORY)
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
            "- For questions like 'where is X' or 'on which pipeline is X', "
            "identify where that tag appears in the pipelines and nodes.\n"
            "- Use the entire conversation history to keep track of context.\n"
            "- Do NOT say that information is not available if it actually appears "
            "anywhere in the JSON context provided to you.\n"
            "- If you genuinely cannot find the information in the JSON, then say "
            "\"this information is not available in the provided data.\""
        ),
    }

# chat_history: ONLY real user & assistant messages that should be displayed and used as memory
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "last_reference" not in st.session_state:
    st.session_state.last_reference = None  # track last tag discussed

# ==========================
# Memory control: reset button
# ==========================
col1, col2 = st.columns([1, 5])
with col1:
    if st.button("🔁 Reset chat / clear memory"):
        st.session_state.chat_history = []
        st.session_state.last_reference = None
        st.rerun()

# ==========================
# Display previous conversation
# (only user + assistant messages, no system)
# ==========================
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ==========================
# Chat Input
# ==========================
user_input = st.chat_input("Ask about any equipment, pipeline, or instrument...")

if user_input:
    # Show user message in UI and store in chat_history (MEMORY)
    st.chat_message("user").markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    # Build local context for CURRENT question
    context = build_local_context(user_input)
    context_text = summarize_context(context)

    # Track last referenced tag (prefer equipment tag, else first pipeline)
    if context["equipment"]:
        st.session_state.last_reference = context["equipment"][0].get("Tag", None)
    elif context["pipelines"]:
        st.session_state.last_reference = list(context["pipelines"].keys())[0]

    # ==========================
    # Prepare messages for the model
    # MEMORY = entire chat_history is included here
    # ==========================
    messages = (
        [st.session_state.system_message]
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

    # Show assistant reply and store in chat_history (MEMORY)
    st.chat_message("assistant").markdown(reply)
    st.session_state.chat_history.append({"role": "assistant", "content": reply})
