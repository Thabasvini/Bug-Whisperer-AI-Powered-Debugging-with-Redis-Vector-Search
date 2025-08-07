import redis
import time
import os
from dotenv import load_dotenv

load_dotenv()
r = redis.Redis.from_url(os.getenv("REDIS_URL"))

stream_name = "bug_logs"

errors = [
    {"error": "NameError: name 'x' is not defined"},
    {"error": "SyntaxError: unexpected EOF while parsing"},
    {"error": "ConnectionError: Failed to connect to database"},
    {"error": "ZeroDivisionError: division by zero"},
]

print("🚀 Bug Producer started...")
for e in errors:
    r.xadd(stream_name, e)
    print(f"✅ Added: {e}")
    time.sleep(2)
