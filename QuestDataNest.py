import sqlite3
from pathlib import Path

from wizwalker import Client
from wizwalker.memory.memory_objects.client_tag_list import ClientTagList
from wizwalker.memory.memory_objects.quest_data import QuestData
from wizwalker.memory.memory_objects.madlib_block import MadlibBlock
from wizwalker.memory.memory_objects.madlib_arg import MadlibArg
from wizwalker.memory.memory_objects.goal_data import GoalData

class Utils:
    @staticmethod
    async def translate_lang_key(client: Client, lang_key: str) -> str:
        """
        Tries to translate a string using the langcode cache.
        If the lookup fails or the key is empty, it returns the original string.
        """
        if not lang_key:
            return ""

        try:
            return await client.cache_handler.get_langcode_name(lang_key)
        except Exception as e:
            return lang_key


class QuestDatabase:
    def __init__(self, db_path: str = "quests.db"):
        """Initializes the database connection and creates tables if they don't exist."""
        # --- FIX: Hardcoding the absolute path as requested for reliability ---
        hardcoded_path = r"C:\Github Repos Python\QuestWhiz\quests.db"
        self.db_path = Path(hardcoded_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path)
        self._create_tables()

    def drop_all_tables(self):
        """Drops all known tables from the database to allow for a clean rebuild."""
        cursor = self.conn.cursor()
        print("Dropping existing tables to apply new schema...")
        cursor.execute('DROP TABLE IF EXISTS quests')
        cursor.execute('DROP TABLE IF EXISTS goals')
        cursor.execute('DROP TABLE IF EXISTS goal_client_tags')
        cursor.execute('DROP TABLE IF EXISTS madlibs')
        self.conn.commit()

    def _create_tables(self):
        """Creates the necessary SQLite tables with the full, corrected schema."""
        cursor = self.conn.cursor()

        cursor.execute(
            'CREATE TABLE IF NOT EXISTS quests (quest_id TEXT PRIMARY KEY, name TEXT, raw_name_key TEXT, is_mainline BOOLEAN, quest_level INTEGER, activity_type TEXT, quest_type INTEGER, permit_quest_helper BOOLEAN, pet_only_quest BOOLEAN)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS goals (goal_id TEXT PRIMARY KEY, quest_id TEXT, name TEXT, raw_name_key TEXT, goal_type TEXT, destination_zone TEXT, status BOOLEAN, no_quest_helper BOOLEAN, pet_only_goal BOOLEAN, has_active_results BOOLEAN, hide_floaty_text BOOLEAN, FOREIGN KEY (quest_id) REFERENCES quests (quest_id))')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS goal_client_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, quest_id TEXT, goal_id TEXT, tag TEXT, FOREIGN KEY (goal_id) REFERENCES goals (goal_id))')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS madlibs (id INTEGER PRIMARY KEY AUTOINCREMENT, quest_id TEXT, goal_id TEXT, identifier TEXT, final_value TEXT, FOREIGN KEY (goal_id) REFERENCES goals (goal_id))')

        self.conn.commit()

    async def log_quest(self, client: Client, quest: QuestData, quest_id: int):
        """Logs a QuestData object to the database with all fields."""
        cursor = self.conn.cursor()

        name = await Utils.translate_lang_key(client, await quest.name_lang_key())
        raw_name = await quest.name_lang_key()
        is_mainline = await quest.mainline()
        level = await quest.quest_level()
        activity = (await quest.activity_type()).name
        q_type = await quest.quest_type()
        permit_helper = await quest.permit_quest_helper()
        pet_only = await quest.pet_only_quest()

        cursor.execute(
            'INSERT OR REPLACE INTO quests (quest_id, name, raw_name_key, is_mainline, quest_level, activity_type, quest_type, permit_quest_helper, pet_only_quest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (str(quest_id), name, raw_name, is_mainline, level, activity, q_type, permit_helper, pet_only))

        self.conn.commit()

    async def log_goal(self, client: Client, goal: GoalData, goal_id: int, parent_quest_id: int):
        """Logs a GoalData object and its children (tags, madlibs) to the database."""
        cursor = self.conn.cursor()

        name = await Utils.translate_lang_key(client, await goal.name_lang_key())
        raw_name = await goal.name_lang_key()
        goal_type = (await goal.goal_type()).name
        dest_zone = await goal.goal_destination_zone()
        status = await goal.goal_status()
        no_helper = await goal.no_quest_helper()
        pet_only = await goal.pet_only_quest()
        has_results = await goal.has_active_results()
        hide_floaty = await goal.hide_goal_floaty_text()

        cursor.execute(
            'INSERT OR REPLACE INTO goals (goal_id, quest_id, name, raw_name_key, goal_type, destination_zone, status, no_quest_helper, pet_only_goal, has_active_results, hide_floaty_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (str(goal_id), str(parent_quest_id), name, raw_name, goal_type, dest_zone, status, no_helper, pet_only,
             has_results, hide_floaty))

        # Log associated client tags, now passing the quest_id
        tag_list = await goal.client_tag_list()
        if tag_list:
            await self.log_client_tags(tag_list, goal_id, parent_quest_id)

        # Log associated madlibs, now passing the quest_id
        madlib_block = await goal.madlib_block()
        if madlib_block:
            entries = await madlib_block.entries()
            for entry in entries:
                await self.log_madlib(client, entry, goal_id, parent_quest_id)

        self.conn.commit()

    async def log_client_tags(self, client_tag_list: ClientTagList, parent_goal_id: int, parent_quest_id: int):
        """Logs a list of client tags for a given goal, including the parent quest_id."""
        cursor = self.conn.cursor()
        tags = await client_tag_list.client_tags()
        for tag in tags:
            cursor.execute('INSERT INTO goal_client_tags (quest_id, goal_id, tag) VALUES (?, ?, ?)',
                           (str(parent_quest_id), str(parent_goal_id), tag))

    async def log_madlib(self, client: Client, madlib: MadlibArg, parent_goal_id: int, parent_quest_id: int):
        """Logs a MadlibArg object to the database, including the parent quest_id."""
        cursor = self.conn.cursor()

        identifier = await Utils.translate_lang_key(client, await madlib.identifier())
        raw_value = await madlib.maybe_data_str()
        final_value = await Utils.translate_lang_key(client, raw_value)

        cursor.execute('INSERT INTO madlibs (quest_id, goal_id, identifier, final_value) VALUES (?, ?, ?, ?)',
                       (str(parent_quest_id), str(parent_goal_id), identifier, final_value or "Empty"))

    def close(self):
        """Closes the database connection."""
        self.conn.close()