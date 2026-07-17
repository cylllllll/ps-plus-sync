import unittest
from unittest.mock import patch

import sync


def make_valid_schema():
    schema = {"游戏名称": {"type": "title", "title": {}}}
    for name, property_type in sync.CORE_PROPERTY_TYPES.items():
        schema[name] = {"type": property_type, property_type: {}}
    for name, property_type in sync.MANAGED_PROPERTY_TYPES.items():
        schema[name] = {"type": property_type, property_type: {}}
    return schema


class FakeDataSources:
    def __init__(self, properties):
        self.properties = properties
        self.updates = []

    def retrieve(self, data_source_id):
        return {"id": data_source_id, "properties": self.properties}

    def update(self, data_source_id, properties):
        self.updates.append((data_source_id, properties))
        for name, definition in properties.items():
            property_type = next(iter(definition))
            self.properties[name] = {
                "type": property_type,
                property_type: definition[property_type],
            }
        return {"id": data_source_id, "properties": self.properties}


class FakeNotion:
    def __init__(self, properties):
        self.data_sources = FakeDataSources(properties)


class SyncHelpersTest(unittest.TestCase):
    def test_build_game_properties_does_not_stamp_unchanged_rows(self):
        game = {
            "tier": "2档",
            "device": ["PS5"],
            "genre": ["ACTION"],
            "streamingSupported": False,
            "releaseDate": "2026-07-01T00:00:00Z",
            "conceptUrl": "https://example.com/game",
            "imageUrl": "https://example.com/cover.png",
            "conceptId": 123,
            "productId": "PRODUCT-ID",
            "ageRating": "IARC 12+",
        }

        properties = sync.build_game_properties(game)

        self.assertNotIn("最后更新时间", properties)

    def test_schema_validation_refuses_the_wrong_data_source(self):
        fake_notion = FakeNotion({"Name": {"type": "title", "title": {}}})

        with patch.object(sync, "notion", fake_notion), patch.object(
            sync, "DATA_SOURCE_ID", "wrong-source"
        ):
            with self.assertRaisesRegex(RuntimeError, "not the PS Plus"):
                sync.ensure_data_source_schema()

        self.assertEqual(fake_notion.data_sources.updates, [])

    def test_schema_validation_adds_missing_last_updated_property(self):
        schema = make_valid_schema()
        schema.pop("最后更新时间")
        fake_notion = FakeNotion(schema)

        with patch.object(sync, "notion", fake_notion), patch.object(
            sync, "DATA_SOURCE_ID", "correct-source"
        ):
            title_property = sync.ensure_data_source_schema()

        self.assertEqual(title_property, "游戏名称")
        self.assertEqual(
            fake_notion.data_sources.updates,
            [
                (
                    "correct-source",
                    {"最后更新时间": {"date": {}}},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
