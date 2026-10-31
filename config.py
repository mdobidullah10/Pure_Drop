import os
import urllib.parse
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    encoded_pw = urllib.parse.quote_plus("Obidullah@910")
    DATABASE_URL = f"postgresql://postgres.mnkpqucsbllsthzjadto:{encoded_pw}@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

# Legacy fallback SQLite path if explicitly requested
SQLITE_PATH = os.path.join(BASE_DIR, "pure_drop.db")
USE_SUPABASE = os.environ.get("USE_SUPABASE", "true").lower() == "true"
