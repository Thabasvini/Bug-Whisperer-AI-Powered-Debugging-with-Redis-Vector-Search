import streamlit as st
import os
import json
import redis
import numpy as np
from dotenv import load_dotenv
from transformers import pipeline
from sentence_transformers import SentenceTransformer, util
import torch

# Load .env
load_dotenv()

# Redis connection
r = redis.Redis.from_url(os.getenv("REDIS_URL"))

# Models
embedding_model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
explain_model = pipeline("text2text-generation", model="google/flan-t5-base", device=-1)

# Page Config
st.set_page_config(page_title="Bug Whisperer", layout="wide")
st.markdown("<h1 style='text-align: center;'>🐞 Bug Whisperer AI Dashboard</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>Your AI-powered debugging assistant – spot, explain, and resolve bugs fast!</p>", unsafe_allow_html=True)

# ------------------------
# SECTION 1: LIVE BUG LOGS
# ------------------------
st.subheader("🔴 Recent Bug Reports")

with st.expander("📜 View last 10 bug reports", expanded=True):
    bug_keys = r.lrange("bug_index", -10, -1)
    if bug_keys:
        for key in reversed(bug_keys):
            data = r.hgetall(key)
            error = data[b'error'].decode()
            suggestion = data[b'suggestion'].decode()
            severity = data[b'severity'].decode()

            severity_color = {
                "Critical": "red",
                "Warning": "orange",
                "Info": "green"
            }.get(severity, "gray")

            st.markdown(f"""
                <div style="border:1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 10px;">
                    <span style="color:{severity_color}; font-weight:bold;">Severity: {severity}</span><br>
                    <b>Error:</b> <code>{error}</code><br>
                    <b>Suggestion:</b> {suggestion}
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No bugs found in the log yet.")

# ------------------------
# SECTION 2: CHATBOT
# ------------------------
st.subheader("🤖 Ask the Bug Whisperer")

with st.form("bug_form"):
    user_input = st.text_area("💬 Enter your bug/error message below", height=150, placeholder="Paste full error message here...")
    submitted = st.form_submit_button("🔍 Get Suggestion")

# ------------------------
# Helper Functions
# ------------------------
def classify_severity(error_text):
    if any(k in error_text for k in ["ConnectionError", "ZeroDivisionError"]):
        return "Critical"
    elif "SyntaxError" in error_text:
        return "Warning"
    elif "NameError" in error_text:
        return "Info"
    else:
        return "Info"

def template_fallback(error_text):
    if "ZeroDivisionError" in error_text:
        return "Cause: Division by zero.\nFix: Check denominator before dividing."
    elif "NameError" in error_text:
        return "Cause: A variable was used before being defined.\nFix: Ensure the variable is initialized."
    elif "SyntaxError" in error_text:
        return "Cause: Code syntax is invalid.\nFix: Review and correct code syntax."
    elif "ConnectionError" in error_text:
        return "Cause: Failed to connect to the database.\nFix: Verify host, port, and credentials."
    return None

def find_similar_bug(new_emb):
    new_emb_tensor = torch.tensor(new_emb, dtype=torch.float32)
    bug_entries = r.hgetall("bug_suggestions")
    for key, val in bug_entries.items():
        entry = json.loads(val)
        old_emb = torch.tensor(entry["embedding"], dtype=torch.float32)
        sim = util.cos_sim(new_emb_tensor, old_emb)[0][0].item()
        if sim > 0.9:
            return entry
    return None

def generate_suggestion(error_text):
    severity = classify_severity(error_text)
    error_embedding = embedding_model.encode(error_text, convert_to_tensor=True).cpu().numpy()

    found = find_similar_bug(error_embedding)
    if found:
        return f"💾 Retrieved from memory ({severity}):\n\n{found['suggestion']}"

    # Try fallback first
    fallback = template_fallback(error_text)
    if fallback:
        # Save to Redis for reuse
        new_entry = {
            "embedding": error_embedding.tolist(),
            "suggestion": fallback,
            "severity": severity,
        }
        r.hset("bug_suggestions", error_text, json.dumps(new_entry))
        r.hset(error_text, mapping={
            "error": error_text,
            "suggestion": fallback,
            "severity": severity,
        })
        r.rpush("bug_index", error_text)
        return f"🤖 Suggestion ({severity}):\n\n{fallback}"

    # If no fallback, generate using model
    prompt = f"Explain this error and suggest a fix:\nError: {error_text}"
    result = explain_model(prompt, max_length=120, do_sample=False)
    raw = result[0]['generated_text'].strip()

    if "Fix:" not in raw:
        raw = (
            f"Cause: Likely reason for '{error_text}'.\n"
            f"Fix: Please verify configuration, syntax, or logic."
        )

    # Save model response to Redis
       
    new_entry = {
        "embedding": error_embedding.tolist(),
        "suggestion": raw,
        "severity": severity,
    }
    r.hset("bug_suggestions", error_text, json.dumps(new_entry))
    r.hset(error_text, mapping={
        "error": error_text,
        "suggestion": raw,
        "severity": severity,
    })
    r.rpush("bug_index", error_text)


    return f"🤖 Suggestion ({severity}):\n\n{raw}"


# ------------------------
# Result Display
# ------------------------
if submitted and user_input.strip():
    with st.spinner("🔍 Analyzing your bug..."):
        response = generate_suggestion(user_input.strip())
        st.success(response)
