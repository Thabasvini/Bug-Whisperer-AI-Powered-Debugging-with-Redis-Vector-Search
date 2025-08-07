import redis, os, json
import numpy as np
from dotenv import load_dotenv
from transformers import pipeline
from sentence_transformers import SentenceTransformer, util
import torch


# Load environment
load_dotenv()
r = redis.Redis.from_url(os.getenv("REDIS_URL"))

stream_name = "bug_logs"
last_id = "0-0"

print("🤖 Bug Whisperer AI Consumer started...")

# Load models
explain_model = pipeline("text2text-generation", model="google/flan-t5-base")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

# Severity classifier
def classify_severity(error_text):
    if any(k in error_text for k in ["ConnectionError", "ZeroDivisionError"]):
        return "Critical"
    elif "SyntaxError" in error_text:
        return "Warning"
    elif "NameError" in error_text:
        return "Info"
    else:
        return "Info"

# Template fallback
def template_fallback(error_text):
    if "ZeroDivisionError" in error_text:
        return "Cause: Division by zero.\nFix: Check denominator before dividing."
    elif "NameError" in error_text:
        return "Cause: A variable was used before being defined.\nFix: Ensure the variable is initialized."
    elif "SyntaxError" in error_text:
        return "Cause: Code syntax is invalid.\nFix: Review and correct code syntax."
    elif "ConnectionError" in error_text:
        return "Cause: Failed to connect to the database.\nFix: Verify host, port, and credentials."
    else:
        return None

# Check Redis for similar bug
def find_similar_bug(new_emb, threshold=0.8):
    bug_keys = r.lrange("bug_index", 0, -1)
    for key in bug_keys:
        data = r.hgetall(key)
        old_emb = np.array(json.loads(data[b'embedding'].decode()), dtype=np.float32)  # force float32
        sim = util.cos_sim(
            torch.tensor(new_emb, dtype=torch.float32),
            torch.tensor(old_emb, dtype=torch.float32)
        )[0][0].item()
        if sim >= threshold:
            return data[b'suggestion'].decode()
    return None

# Store new bug into Redis
def store_bug(error, suggestion, severity, embedding):
    bug_id = f"bug:{r.incr('bug_counter')}"
    r.hset(bug_id, mapping={
        "error": error,
        "suggestion": suggestion,
        "severity": severity,
        "embedding": json.dumps(embedding.tolist())
    })
    r.rpush("bug_index", bug_id)

# Main consumer loop
while True:
    messages = r.xread({stream_name: last_id}, block=0)
    for stream, events in messages:
        for msg_id, msg in events:
            error_text = msg[b'error'].decode()
            print(f"\n🐞 Bug detected: {error_text}")

            severity = classify_severity(error_text)
            error_embedding = embedding_model.encode(error_text, convert_to_tensor=True).cpu().numpy()

            found = find_similar_bug(error_embedding)
            if found:
                print(f"💡 From memory ({severity}):\n{found}")
            else:
                suggestion = template_fallback(error_text)
                if not suggestion:
                    prompt = f"Explain this error and suggest a fix:\nError: {error_text}"
                    result = explain_model(prompt, max_length=120, do_sample=False)
                    raw = result[0]['generated_text'].strip()
                    if "Fix:" not in raw:
                        suggestion = (
                            f"Cause: Likely reason for '{error_text}'.\n"
                            f"Fix: Please verify configuration, syntax, or logic."
                        )
                    else:
                        suggestion = raw

                print(f"🤖 Suggestion ({severity}):\n{suggestion}")
                store_bug(error_text, suggestion, severity, error_embedding)

            last_id = msg_id.decode()
