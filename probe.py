import os
from dotenv import load_dotenv
from notion_client import Client

load_dotenv()
notion = Client(auth=os.getenv("NOTION_API_KEY"))
db_id = os.getenv("NOTION_DATABASE_ID", "").replace("-", "")

res = notion.search(filter={"property": "object", "value": "page"}, page_size=5)
for r in res.get("results", []):
    if r.get("parent", {}).get("database_id", "").replace("-", "") == db_id:
        print("Schema:", list(r["properties"].keys()))
        break
