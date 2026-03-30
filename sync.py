import os
import json
import urllib.request
import logging
from datetime import datetime
from dotenv import load_dotenv
from notion_client import Client, APIResponseError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").replace("-", "")

if not NOTION_TOKEN or not DATABASE_ID:
    logging.error("Missing NOTION_API_KEY or NOTION_DATABASE_ID in .env/environment")
    exit(1)

notion = Client(auth=NOTION_TOKEN)

def fetch_ps_catalog():
    categories = {
        "plus-games-list": "2档",
        "ubisoft-classics-list": "2档",
        "plus-classics-list": "3档",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    catalog_games = {}
    
    for cat, tier in categories.items():
        url = f"https://www.playstation.com/bin/imagic/gameslist?locale=zh-hans-hk&categoryList={cat}"
        logging.info(f"Fetching {cat} ({tier})...")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                
            for group in data:
                if "games" in group:
                    for game in group["games"]:
                        name = game.get("name", "").strip()
                        if not name: continue
                        name_en = game.get("nameEn", "").strip()
                        devices = game.get("device", [])
                        
                        key = name.lower()
                        if key not in catalog_games:
                            catalog_games[key] = {
                                "name": name,
                                "nameEn": name_en,
                                "device": devices,
                                "tier": tier,
                                "releaseDate": game.get("releaseDate", "")
                            }
        except Exception as e:
            logging.error(f"Error fetching {cat}: {e}")
            
    return catalog_games

def get_title_property_name(page):
    props = page.get("properties", {})
    for key, value in props.items():
        if value.get("type") == "title":
            return key
    return "Name"

def get_page_title(page):
    props = page.get("properties", {})
    for key, value in props.items():
        if value.get("type") == "title":
            title_arr = value.get("title", [])
            if title_arr:
                return title_arr[0].get("plain_text", "").strip()
    return ""

def fetch_notion_games():
    logging.info("Fetching existing games from Notion via Search API...")
    notion_games = {}
    title_prop_name = "Name"
    
    has_more = True
    next_cursor = None
    
    while has_more:
        kwargs = {
            "filter": {"property": "object", "value": "page"}
        }
        if next_cursor:
            kwargs["start_cursor"] = next_cursor
            
        try:
            res = notion.search(**kwargs)
        except APIResponseError as e:
            logging.error(f"Notion API Error: {e}")
            break
            
        for page in res.get("results", []):
            parent_db = page.get("parent", {}).get("database_id", "").replace("-", "")
            if parent_db != DATABASE_ID:
                continue
            
            if len(notion_games) == 0:
                title_prop_name = get_title_property_name(page)
            
            title = get_page_title(page)
            if not title: continue
            
            props = page.get("properties", {})
            
            # get en_name
            en_name = ""
            en_prop = props.get("英文名称", {})
            if en_prop.get("type") == "rich_text" and en_prop.get("rich_text"):
                en_name = en_prop["rich_text"][0].get("plain_text", "").strip()
            
            status = ""
            if "状态" in props and props.get("状态", {}).get("select"):
                status = props["状态"]["select"].get("name", "")
                
            tier = ""
            if "档位" in props and props.get("档位", {}).get("select"):
                tier = props["档位"]["select"].get("name", "")
                
            game_data = {
                "id": page["id"],
                "status": status,
                "tier": tier,
                "page": page
            }
            
            notion_games[title.lower()] = game_data
            if en_name:
                notion_games[en_name.lower()] = game_data
            
        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor", None)
        
    return notion_games, title_prop_name

def sync_games():
    catalog_games = fetch_ps_catalog()
    notion_games, title_prop_name = fetch_notion_games()
    
    logging.info(f"Fetched {len(catalog_games)} games from PS Catalog.")
    # notion_games counts title and en_name as keys, so actual unique games is smaller.
    
    added_count = 0
    updated_count = 0
    
    # 1. Add new games
    for key, ps_game in catalog_games.items():
        name_key = ps_game["name"].lower()
        en_key = ps_game["nameEn"].lower()
        
        if name_key not in notion_games and (not en_key or en_key not in notion_games):
            logging.info(f"New Game Detected: {ps_game['name']} ({ps_game['tier']}) - Adding to Notion...")
            
            properties = {
                title_prop_name: {
                    "title": [{"text": {"content": ps_game["name"]}}]
                },
                "英文名称": {
                    "rich_text": [{"text": {"content": ps_game["nameEn"]}}]
                },
                "档位": {
                    "select": {"name": ps_game["tier"]}
                },
                "状态": {
                    "select": {"name": "在库"}
                },
                "入库日期": {
                    "date": {"start": datetime.utcnow().strftime("%Y-%m-%d")}
                },
                "版本": {
                    "multi_select": [{"name": dev} for dev in ps_game["device"] if dev]
                }
            }
            
            try:
                notion.pages.create(
                    parent={"database_id": DATABASE_ID},
                    properties=properties
                )
                added_count += 1
            except APIResponseError as e:
                logging.error(f"Failed to add {ps_game['name']}: {e}")
                
    # 2. Update removed games
    # Reverse map catalog to easily check if a notion game is still in the catalog
    catalog_names = set([g["name"].lower() for g in catalog_games.values()] + [g["nameEn"].lower() for g in catalog_games.values() if g["nameEn"]])
    
    # Use a set for unique IDs to avoid processing the same page twice
    processed_ids = set()
    
    for key, notion_game in notion_games.items():
        page_id = notion_game["id"]
        if page_id in processed_ids:
            continue
        processed_ids.add(page_id)
        
        if notion_game["tier"] in ["2档", "3档"] and notion_game["status"] == "在库":
            title = get_page_title(notion_game["page"])
            en_prop = notion_game["page"].get("properties", {}).get("英文名称", {})
            en_name = en_prop.get("rich_text", [{}])[0].get("plain_text", "").strip() if en_prop.get("rich_text") else ""
            
            # Check if it exists in the currently fetched catalog
            if title.lower() not in catalog_names and (not en_name or en_name.lower() not in catalog_names):
                logging.info(f"Game Left Catalog: {title} - Updating Status to 已出库...")
                try:
                    notion.pages.update(
                        page_id=page_id,
                        properties={
                            "状态": {"select": {"name": "已出库"}},
                            "出库日期": {"date": {"start": datetime.utcnow().strftime("%Y-%m-%d")}}
                        }
                    )
                    updated_count += 1
                except APIResponseError as e:
                    logging.error(f"Failed to update {title}: {e}")
                    
    logging.info(f"Sync complete. Added: {added_count}, Updated to left catalog: {updated_count}.")

if __name__ == "__main__":
    sync_games()
