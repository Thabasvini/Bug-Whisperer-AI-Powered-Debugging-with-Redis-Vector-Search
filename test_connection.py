import redis, os
from dotenv import load_dotenv

load_dotenv()
r = redis.Redis.from_url(os.getenv("REDIS_URL"))

try:
    print("✅ PONG:", r.ping())
except Exception as e:
    print("❌ Connection failed:", e)
