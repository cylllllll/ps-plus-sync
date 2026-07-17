import os
import json
import urllib.request
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from notion_client import Client, APIResponseError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_API_KEY")
DATA_SOURCE_ID = os.getenv("NOTION_DATA_SOURCE_ID", "").replace("-", "")
NOTION_API_VERSION = "2025-09-03"

notion = (
    Client(auth=NOTION_TOKEN, notion_version=NOTION_API_VERSION)
    if NOTION_TOKEN and DATA_SOURCE_ID
    else None
)

CORE_PROPERTY_TYPES = {
    "英文名称": "rich_text",
    "档位": "select",
    "状态": "select",
    "版本": "multi_select",
    "入库日期": "date",
    "出库日期": "date",
}

MANAGED_PROPERTY_SCHEMAS = {
    "类型": {"multi_select": {}},
    "发售日": {"date": {}},
    "商店链接": {"url": {}},
    "封面链接": {"url": {}},
    "Concept ID": {"number": {"format": "number"}},
    "Product ID": {"rich_text": {}},
    "支持串流": {"checkbox": {}},
    "年龄评级": {"select": {}},
    "最后更新时间": {"date": {}},
}

MANAGED_PROPERTY_TYPES = {
    name: next(iter(schema))
    for name, schema in MANAGED_PROPERTY_SCHEMAS.items()
}

def fetch_ps_catalog():
    categories = {
        "plus-games-list": "2档",
        "ubisoft-classics-list": "2档",
        "plus-classics-list": "3档",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    catalog_games = {}
    
    failed_categories = []

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
                        
                        ageRating = game.get("ageRating", {}).get("description", "")
                        if not ageRating:
                            ageRating = game.get("ageRating", {}).get("name", "")
                        
                        key = name.lower()
                        if key not in catalog_games:
                            catalog_games[key] = {
                                "name": name,
                                "nameEn": name_en,
                                "device": devices,
                                "tier": tier,
                                "releaseDate": game.get("releaseDate", ""),
                                "genre": game.get("genre", []),
                                "conceptUrl": game.get("conceptUrl", ""),
                                "imageUrl": game.get("imageUrl", ""),
                                "conceptId": game.get("conceptId", None),
                                "productId": game.get("productId", ""),
                                "streamingSupported": game.get("streamingSupported", False),
                                "ageRating": ageRating
                            }
        except Exception as e:
            logging.error(f"Error fetching {cat}: {e}")
            failed_categories.append(cat)

    if failed_categories:
        raise RuntimeError(
            "Refusing to sync an incomplete PS catalog; failed categories: "
            + ", ".join(failed_categories)
        )

    return catalog_games

def validate_property_types(properties, expected_types):
    mismatches = []
    for name, expected_type in expected_types.items():
        actual_type = properties.get(name, {}).get("type")
        if actual_type != expected_type:
            mismatches.append(f"{name}: expected {expected_type}, got {actual_type or 'missing'}")
    return mismatches


def ensure_data_source_schema():
    logging.info("Validating Notion data source and required properties...")
    data_source = notion.data_sources.retrieve(data_source_id=DATA_SOURCE_ID)
    properties = data_source.get("properties", {})

    title_properties = [
        name for name, value in properties.items() if value.get("type") == "title"
    ]
    if len(title_properties) != 1:
        raise RuntimeError(
            f"Expected exactly one title property, found {len(title_properties)}."
        )

    core_mismatches = validate_property_types(properties, CORE_PROPERTY_TYPES)
    if core_mismatches:
        raise RuntimeError(
            "Configured Notion data source is not the PS Plus subscription catalog: "
            + "; ".join(core_mismatches)
        )

    missing_managed_properties = {
        name: schema
        for name, schema in MANAGED_PROPERTY_SCHEMAS.items()
        if name not in properties
    }
    if missing_managed_properties:
        logging.info(
            "Adding missing managed properties: %s",
            ", ".join(missing_managed_properties),
        )
        notion.data_sources.update(
            data_source_id=DATA_SOURCE_ID,
            properties=missing_managed_properties,
        )
        data_source = notion.data_sources.retrieve(data_source_id=DATA_SOURCE_ID)
        properties = data_source.get("properties", {})

    managed_mismatches = validate_property_types(properties, MANAGED_PROPERTY_TYPES)
    if managed_mismatches:
        raise RuntimeError(
            "Notion managed property validation failed: "
            + "; ".join(managed_mismatches)
        )

    logging.info("Notion data source schema validated successfully.")
    return title_properties[0]

def get_page_title(page):
    props = page.get("properties", {})
    for key, value in props.items():
        if value.get("type") == "title":
            title_arr = value.get("title", [])
            if title_arr:
                return title_arr[0].get("plain_text", "").strip()
    return ""


def fetch_notion_games():
    logging.info("Fetching existing games from the Notion data source...")
    notion_games = {}
    
    has_more = True
    next_cursor = None
    
    while has_more:
        kwargs = {"data_source_id": DATA_SOURCE_ID}
        if next_cursor:
            kwargs["start_cursor"] = next_cursor
            
        try:
            res = notion.data_sources.query(**kwargs)
        except APIResponseError as e:
            raise RuntimeError(f"Notion data source query failed: {e}") from e
            
        for page in res.get("results", []):
            title = get_page_title(page)
            if not title: continue
            
            props = page.get("properties", {})
            
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
        
    return notion_games


def build_game_properties(ps_game):
    properties = {
        "档位": {"select": {"name": ps_game["tier"]}},
        "状态": {"select": {"name": "在库"}},
        "版本": {
            "multi_select": [
                {"name": device} for device in ps_game["device"] if device
            ]
        },
        "类型": {
            "multi_select": [
                {"name": genre} for genre in ps_game["genre"] if genre
            ]
        },
        "支持串流": {"checkbox": ps_game["streamingSupported"]},
    }

    if ps_game["releaseDate"]:
        properties["发售日"] = {"date": {"start": ps_game["releaseDate"][:10]}}
    if ps_game["conceptUrl"]:
        properties["商店链接"] = {"url": ps_game["conceptUrl"]}
    if ps_game["imageUrl"]:
        properties["封面链接"] = {"url": ps_game["imageUrl"]}
    if ps_game["conceptId"]:
        properties["Concept ID"] = {"number": int(ps_game["conceptId"])}
    if ps_game["productId"]:
        properties["Product ID"] = {
            "rich_text": [{"text": {"content": ps_game["productId"]}}]
        }
    if ps_game["ageRating"]:
        properties["年龄评级"] = {
            "select": {"name": ps_game["ageRating"][:100]}
        }

    return properties


def property_matches(existing, desired):
    if "select" in desired:
        existing_value = existing.get("select") or {}
        desired_value = desired.get("select") or {}
        return existing_value.get("name") == desired_value.get("name")
    if "multi_select" in desired:
        existing_names = sorted(
            item.get("name", "") for item in existing.get("multi_select", [])
        )
        desired_names = sorted(
            item.get("name", "") for item in desired.get("multi_select", [])
        )
        return existing_names == desired_names
    if "checkbox" in desired:
        return existing.get("checkbox", False) == desired["checkbox"]
    if "date" in desired:
        existing_date = existing.get("date") or {}
        desired_date = desired.get("date") or {}
        return existing_date.get("start") == desired_date.get("start")
    if "url" in desired:
        return existing.get("url") == desired["url"]
    if "number" in desired:
        return existing.get("number") == desired["number"]
    if "rich_text" in desired:
        existing_text = "".join(
            item.get("plain_text", "") for item in existing.get("rich_text", [])
        )
        desired_text = "".join(
            item.get("text", {}).get("content", "")
            for item in desired.get("rich_text", [])
        )
        return existing_text == desired_text
    return False


def properties_need_refresh(existing_properties, desired_properties):
    return any(
        not property_matches(existing_properties.get(name, {}), desired)
        for name, desired in desired_properties.items()
    )


def sync_games():
    title_prop_name = ensure_data_source_schema()
    catalog_games = fetch_ps_catalog()
    notion_games = fetch_notion_games()
    sync_timestamp = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    sync_date = sync_timestamp[:10]
    
    logging.info(f"Fetched {len(catalog_games)} games from PS Catalog.")
    
    added_count = 0
    updated_count = 0
    refreshed_count = 0
    write_failure_count = 0
    
    catalog_names = set([g["name"].lower() for g in catalog_games.values()] + [g["nameEn"].lower() for g in catalog_games.values() if g["nameEn"]])
    processed_ids = set()
    
    for ps_game in catalog_games.values():
        name_key = ps_game["name"].lower()
        en_key = ps_game["nameEn"].lower()
        
        properties = build_game_properties(ps_game)
            
        create_kwargs = {
            "parent": {
                "type": "data_source_id",
                "data_source_id": DATA_SOURCE_ID,
            },
            "properties": dict(properties),
        }
        # Add page cover if available
        if ps_game["imageUrl"]:
            create_kwargs["cover"] = {"type": "external", "external": {"url": ps_game["imageUrl"]}}
        
        if name_key not in notion_games and (not en_key or en_key not in notion_games):
            # 1. ADD NEW GAME
            logging.info(f"New Game Detected: {ps_game['name']} - Adding to Notion...")
            create_kwargs["properties"][title_prop_name] = {
                "title": [{"text": {"content": ps_game["name"]}}]
            }
            create_kwargs["properties"]["英文名称"] = {
                "rich_text": [{"text": {"content": ps_game["nameEn"]}}]
            }
            create_kwargs["properties"]["入库日期"] = {
                "date": {"start": sync_date}
            }
            create_kwargs["properties"]["最后更新时间"] = {
                "date": {"start": sync_timestamp}
            }
            
            try:
                notion.pages.create(**create_kwargs)
                added_count += 1
            except APIResponseError as e:
                logging.error(f"Failed to add {ps_game['name']}: {e}")
                write_failure_count += 1
        else:
            # 2. Refresh changed games.
            game_node = notion_games.get(name_key) or notion_games.get(en_key)
            page_id = game_node["id"]
            if page_id in processed_ids:
                continue
            processed_ids.add(page_id)

            existing_properties = game_node["page"].get("properties", {})
            needs_refresh = properties_need_refresh(existing_properties, properties)
            if not needs_refresh:
                continue

            update_properties = dict(properties)
            update_properties["最后更新时间"] = {
                "date": {"start": sync_timestamp}
            }
            logging.info(f"Refreshing existing game: {ps_game['name']}")
            update_kwargs = {"page_id": page_id, "properties": update_properties}
            if ps_game["imageUrl"]:
                update_kwargs["cover"] = {
                    "type": "external",
                    "external": {"url": ps_game["imageUrl"]},
                }
            try:
                notion.pages.update(**update_kwargs)
                refreshed_count += 1
            except APIResponseError as e:
                logging.error(f"Failed to refresh {ps_game['name']}: {e}")
                write_failure_count += 1

    # 3. Handle removed games
    for notion_game in notion_games.values():
        page_id = notion_game["id"]
        if page_id in processed_ids:
            continue
        processed_ids.add(page_id)
        
        if notion_game["tier"] in ["2档", "3档"] and notion_game["status"] == "在库":
            title = get_page_title(notion_game["page"])
            en_prop = notion_game["page"].get("properties", {}).get("英文名称", {})
            en_name = en_prop.get("rich_text", [{}])[0].get("plain_text", "").strip() if en_prop.get("rich_text") else ""
            
            if title.lower() not in catalog_names and (not en_name or en_name.lower() not in catalog_names):
                logging.info(f"Game Left Catalog: {title} - Updating Status to 已出库...")
                try:
                    notion.pages.update(
                        page_id=page_id,
                        properties={
                            "状态": {"select": {"name": "已出库"}},
                            "出库日期": {"date": {"start": sync_date}},
                            "最后更新时间": {"date": {"start": sync_timestamp}},
                        }
                    )
                    updated_count += 1
                except APIResponseError as e:
                    logging.error(f"Failed to update {title}: {e}")
                    write_failure_count += 1

    logging.info(
        "Sync complete. Added: %d, Refreshed: %d, "
        "Updated to Left Catalog: %d, Write Failures: %d.",
        added_count,
        refreshed_count,
        updated_count,
        write_failure_count,
    )
    if write_failure_count:
        raise RuntimeError(f"Notion writes failed for {write_failure_count} games.")


def main():
    missing_config = []
    if not NOTION_TOKEN:
        missing_config.append("NOTION_API_KEY")
    if not DATA_SOURCE_ID:
        missing_config.append("NOTION_DATA_SOURCE_ID")

    if missing_config:
        logging.error(
            "Missing required environment variable(s): %s. "
            "NOTION_DATABASE_ID is no longer accepted; copy the data source ID "
            "from Notion's Manage data sources menu.",
            ", ".join(missing_config),
        )
        return 1

    try:
        sync_games()
    except Exception as e:
        logging.error(f"Sync failed: {e}")
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
