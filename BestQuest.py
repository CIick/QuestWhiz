import inspect
import re
from typing import Any, Coroutine, List, Dict, Tuple
from pathlib import Path
import asyncio
from enum import Enum

import keyboard
from loguru import logger
from wizwalker import Client, ClientHandler, Primitive, Keycode

from QuestDataNest import QuestDatabase
from WorldsCollide import WorldsCollideTP

from wizwalker.memory.memory_objects.client_tag_list import ClientTagList
from wizwalker.memory.memory_objects.quest_data import QuestData
from wizwalker.memory.memory_objects.madlib_block import MadlibBlock
from wizwalker.memory.memory_objects.goal_data import GoalData, GoalType

from paths import quest_name_path, advance_dialog_path, popup_title_path, spiral_door_teleport_path, \
    spiral_door_title_path, npc_range_path, popup_msgtext_path, dungeon_warning_path, spiral_door_exit_path
from utils import get_window_from_path, is_visible_by_path, click_window_by_path


class Utils:
    # <editor-fold desc="Utility Functions">
    @staticmethod
    async def translate_lang_key(client: Client, lang_key: str) -> str:
        if not lang_key:
            return ""
        try:
            return await client.cache_handler.get_langcode_name(lang_key)
        except Exception:
            return lang_key

    @staticmethod
    async def get_on_screen_goal_text(client: Client) -> str:
        try:
            quest_name_window = await get_window_from_path(client.root_window, quest_name_path)
            logger.info(f"On-screen goal text UI element found at base address: {hex(quest_name_window.base_address)}")

            raw_text = await quest_name_window.maybe_text()
            if not raw_text:
                return ""

            clean_text = re.sub(r'<[^>]+>', '', raw_text)
            clean_text = ' '.join(clean_text.split())
            return clean_text
        except Exception as e:
            logger.error(f"Failed to read on-screen goal text: {e}")
            return ""

    @staticmethod
    async def get_quest_zone_name(c: Client) -> str:
        query = await Utils.read_quest_txt(c)
        stopwords = ['<center>', '</center>']
        querywords = query.split()
        resultwords = [word for word in querywords if word.lower() not in stopwords]
        s = ' '.join(resultwords)
        res = re.findall(r"\s+in\s+([^\(]*)", s)
        if len(res) == 0:
            return ''
        return res[0].strip()

    @staticmethod
    async def read_quest_txt(client: Client) -> str:
        try:
            quest_name = await get_window_from_path(client.root_window, quest_name_path)
            quest = await quest_name.maybe_text()
        except Exception:
            quest = ""
        return quest

    @staticmethod
    async def read_spiral_door_title(client: Client) -> str:
        try:
            title_text_path = await get_window_from_path(client.root_window, spiral_door_title_path)
            title = await title_text_path.maybe_text()
        except:
            title = ""
        return title

    @staticmethod
    async def read_popup_text(p: Client) -> str:
        try:
            popup_text_path = await get_window_from_path(p.root_window, popup_msgtext_path)
            txtmsg = await popup_text_path.maybe_text()
        except:
            txtmsg = ""
        return txtmsg

    @staticmethod
    def get_world_from_zone(zone_string: str) -> str:
        if not zone_string or '/' not in zone_string:
            return zone_string
        return zone_string.split('/')[0]
    # </editor-fold>


class BestQuest:
    def __init__(self, client: Client, clients: list[Client], db_logger: QuestDatabase, all_quest_data=None):
        self.client = client
        self.db_logger = db_logger
        self.goal_handlers = {
            GoalType.unknown: self._handle_unimplemented_goal,
            GoalType.bounty: self._handle_bounty_goal,
            GoalType.bountycollect: self._handle_bountycollect_goal,
            GoalType.scavenge: self._handle_scavenge_goal,
            GoalType.persona: self._handle_persona_goal,
            GoalType.waypoint: self._handle_waypoint_goal,
            GoalType.scavengefake: self._handle_scavengefake_goal,
            GoalType.achieverank: self._handle_achieverank_goal,
            GoalType.usage: self._handle_usage_goal,
            GoalType.completequest: self._handle_completequest_goal,
            GoalType.sociarank: self._handle_sociarank_goal,
            GoalType.sociacurrency: self._handle_sociacurrency_goal,
            GoalType.sociaminigame: self._handle_sociaminigame_goal,
            GoalType.sociagiveitem: self._handle_sociagiveitem_goal,
            GoalType.sociagetitem: self._handle_sociagetitem_goal,
            GoalType.collectafterbounty: self._handle_collectafterbounty_goal,
            GoalType.encounter_waypoint_foreach: self._handle_encounter_waypoint_foreach_goal
        }

    # <editor-fold desc="Database and Print Helpers">
    async def log_full_quest_to_db(self, quest_to_log: QuestData, quest_id: int):
        if not self.db_logger: return
        logger.info(f"Logging full data for Quest ID {quest_id} to the database...")
        try:
            await self.db_logger.log_quest(self.client, quest_to_log, quest_id)
            all_goals = await quest_to_log.goal_data()
            for goal_id, goal in all_goals.items():
                await self.db_logger.log_goal(self.client, goal, goal_id, quest_id)
            logger.success(f"Successfully logged Quest ID {quest_id} to the database.")
        except Exception as e:
            logger.error(f"Failed to log quest {quest_id} to database: {e}", exc_info=True)

    async def _print_quest_details(self, quest: QuestData, quest_id: int, client: Client):
        print("\n" + "=" * 60)
        print(
            f"Quest: {await Utils.translate_lang_key(self.client, await quest.name_lang_key())} (ID: {quest_id})\n"
            f"  Raw Key: {await quest.name_lang_key()}\n"
            f"  Ready To Turn in: {await quest.ready_to_turn_in()}\n"
            f"  Activity Type: {await quest.activity_type()}\n"
            f"  Quest Type: {await quest.quest_type()}\n"
            f"  Quest Level: {await quest.quest_level()}\n"
            f"  Quest Arrow: {await quest.permit_quest_helper()}\n"
            f"  Mainline Quest: {await quest.mainline()}\n"
            f"  Pet Only: {await quest.pet_only_quest()}"
        )

        quest_goals = await quest.goal_data()
        print("  Goals:")
        if not quest_goals:
            print("    (No goals found for this quest)")
        else:
            for goal_id, goal in quest_goals.items():
                display_goal_id = goal_id & 0xFFFFFFFF
                print(f"    - Goal ID: {display_goal_id} (Full: {goal_id})")
                await self._print_goal_details(goal, indent=6)

        print("=" * 60)

    async def _print_goal_details(self, goal: GoalData, indent: int):
        indent_str = ' ' * indent
        print(
            f"{indent_str}Raw Name: {await goal.name_lang_key()}\n"
            f"{indent_str}Translated Name: {await Utils.translate_lang_key(self.client, await goal.name_lang_key())}\n"
            f"{indent_str}Status: {'Complete' if await goal.goal_status() else 'Incomplete'}\n"
            f"{indent_str}Destination Zone: {await goal.goal_destination_zone()}\n"
            f"{indent_str}Type: {await goal.goal_type()}\n"
        )
        client_tags = await goal.client_tag_list()
        if client_tags:
            await self._print_client_tags(client_tags, indent + 2)
        madlib = await goal.madlib_block()
        if madlib:
            await self._print_madlib_block(madlib, indent + 2)

    async def _print_client_tags(self, client_tag_list: ClientTagList, indent: int):
        indent_str = ' ' * indent
        try:
            tags = await client_tag_list.client_tags()
            if tags:
                print(f"{indent_str}Client Tags:")
                for i, tag in enumerate(tags):
                    print(f"{indent_str}  - {tag}")
        except Exception as e:
            logger.error(f"Could not read ClientTagList: {e}")

    async def _print_madlib_block(self, madlib_block: MadlibBlock, indent: int):
        indent_str = ' ' * indent
        if not madlib_block:
            return
        print(f"{indent_str}MadlibBlock Entries:")
        entries = await madlib_block.entries()
        for entry in entries:
            identifier = await entry.identifier()
            sub_quest_info_string = await entry.maybe_data_str()
            final_sub_quest_info_string = await Utils.translate_lang_key(self.client, sub_quest_info_string)
            print(f"{indent_str}  - Identifier: {await Utils.translate_lang_key(self.client, identifier)}")
            print(f"{indent_str}    Final Value: {final_sub_quest_info_string or 'Empty'}")

    # </editor-fold>

    # <editor-fold desc="Action Handlers">

    async def _handle_dialogue(self):
        if await is_visible_by_path(self.client, popup_title_path):
            logger.warning("Initial NPC interaction pop-up detected. Pressing 'X' to engage.")
            await self.client.send_key(Keycode.X, 0.1)
            await asyncio.sleep(1.0)

        if await is_visible_by_path(self.client, advance_dialog_path):
            logger.warning("Main dialogue box detected. Clearing it...")
            while await is_visible_by_path(self.client, advance_dialog_path):
                await self.client.send_key(Keycode.X, 0.1)
                await asyncio.sleep(0.5)
            logger.success("Dialogue cleared.")

    async def _handle_sigil_entry(self) -> bool:
        if await is_visible_by_path(self.client, npc_range_path):
            popup_text = await Utils.read_popup_text(self.client)
            if "to enter" in popup_text.lower():
                logger.warning("Dungeon sigil detected. Attempting to enter...")
                await self.client.send_key(Keycode.X, 0.1)
                await asyncio.sleep(1.0)

                if await is_visible_by_path(self.client, dungeon_warning_path):
                    logger.info("Confirming dungeon entry...")
                    await click_window_by_path(self.client, dungeon_warning_path)

                logger.info("Waiting for zone change after entering sigil...")
                while not await self.client.is_loading():
                    await asyncio.sleep(0.2)
                logger.success("Entered dungeon.")
                while await self.client.is_loading():
                    await asyncio.sleep(0.2)
                return True
        return False

    async def _cycle_new_portal(self, location_name: str):
        logger.warning(f"Advanced portal logic for location '{location_name}' is not yet implemented.")
        pass

    async def _handle_spiral_door(self, destination_zone: str) -> bool:
        if not await is_visible_by_path(self.client, spiral_door_teleport_path):
            return False

        logger.info("Spiral Door UI is open. Checking if travel is needed...")

        current_world = Utils.get_world_from_zone(await self.client.zone_name())
        destination_world = Utils.get_world_from_zone(destination_zone)

        if current_world == destination_world:
            logger.info(f"Already in the correct world ('{current_world}'). Closing Spiral Door UI.")
            await click_window_by_path(self.client, spiral_door_exit_path)
            await asyncio.sleep(0.5)
            return False

        portal_title = await Utils.read_spiral_door_title(self.client)
        if "Streamportal" in portal_title or "Nanavator" in portal_title:
            logger.info(f"Detected advanced portal: {portal_title}")
            await self._cycle_new_portal("Unknown")
        else:
            logger.info("Detected standard Spiral Door. Clicking teleport button.")
            await click_window_by_path(self.client, spiral_door_teleport_path, True)

        logger.info("Waiting for world travel to complete...")
        while await self.client.is_loading():
            await asyncio.sleep(0.2)
        logger.success("World travel complete.")
        return True

    # </editor-fold>

    # <editor-fold desc="Movement Logic">
    async def _travel_to_goal_location(self, goal: GoalData):
        destination_zone = await goal.goal_destination_zone()
        max_failed_attempts = 5
        failed_attempts = 0

        while failed_attempts < max_failed_attempts:
            current_zone = await self.client.zone_name()
            if not current_zone:
                await asyncio.sleep(0.5)
                continue

            logger.info(
                f"Travel Loop | Attempt [{failed_attempts + 1}/{max_failed_attempts}] | Destination: '{destination_zone}' | Current: '{current_zone}'")

            if current_zone == destination_zone:
                logger.success("Player is in the correct zone.")
                break

            zone_before_action = current_zone

            # Check for and handle UI elements. If they cause a zone change, the loop will continue and re-evaluate.
            await self._handle_spiral_door(destination_zone)
            await self._handle_sigil_entry()
            await self._handle_dialogue()

            if await self.client.zone_name() != zone_before_action:
                logger.success("UI interaction resulted in a zone change. Re-evaluating position.")
                continue

            logger.warning("No interactive zoning UI available. Using WorldsCollideTP to move closer...")
            try:
                await WorldsCollideTP(self.client)
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.error(f"An error occurred during WorldsCollideTP: {e}", exc_info=True)
                failed_attempts += 1
                continue

            if await self.client.zone_name() == zone_before_action:
                logger.error("No progress made in this travel attempt.")
                failed_attempts += 1
        else:
            logger.error(
                f"Failed to reach destination zone '{destination_zone}' after {max_failed_attempts} failed attempts.")
            return

        logger.info("Performing final teleport to precise waypoint location...")
        await WorldsCollideTP(self.client)
        # Final UI check after arriving at the exact spot
        await self._handle_dialogue()
        await self._handle_sigil_entry()  # Check for sigils at final location too
        logger.success("Arrived at final quest location.")

    # </editor-fold>

    # <editor-fold desc="Goal Handlers">
    async def _handle_waypoint_goal(self, goal: GoalData):
        logger.info("Handling WAYPOINT goal")
        await self._travel_to_goal_location(goal)

    async def _handle_persona_goal(self, goal: GoalData):
        logger.info("Handling PERSONA goal...")
        await self._travel_to_goal_location(goal)
        await self._handle_dialogue()

    async def _handle_usage_goal(self, goal: GoalData):
        logger.info("Handling USAGE goal. Not implemented yet.")

    async def _handle_bounty_goal(self, goal: GoalData):
        logger.info("Handling BOUNTY goal. Not implemented yet.")

    async def _handle_bountycollect_goal(self, goal: GoalData):
        logger.info("Handling BOUNTYCOLLECT goal. Not implemented yet.")

    async def _handle_scavenge_goal(self, goal: GoalData):
        logger.info("Handling SCAVENGE goal. Not implemented yet.")

    async def _handle_scavengefake_goal(self, goal: GoalData):
        logger.info("Handling SCAVENGEFAKE goal. Not implemented yet.")

    async def _handle_achieverank_goal(self, goal: GoalData):
        logger.info("Handling ACHIEVERANK goal. Not implemented yet.")

    async def _handle_completequest_goal(self, goal: GoalData):
        logger.info("Handling COMPLETEQUEST goal. Not implemented yet.")

    async def _handle_sociarank_goal(self, goal: GoalData):
        logger.info("Handling SOCIARANK goal. Not implemented yet.")

    async def _handle_sociacurrency_goal(self, goal: GoalData):
        logger.info("Handling SOCIACURRENCY goal. Not implemented yet.")

    async def _handle_sociaminigame_goal(self, goal: GoalData):
        logger.info("Handling SOCIAMINIGAME goal. Not implemented yet.")

    async def _handle_sociagiveitem_goal(self, goal: GoalData):
        logger.info("Handling SOCIAGIVEITEM goal. Not implemented yet.")

    async def _handle_sociagetitem_goal(self, goal: GoalData):
        logger.info("Handling SOCIAGETITEM goal. Not implemented yet.")

    async def _handle_collectafterbounty_goal(self, goal: GoalData):
        logger.info("Handling COLLECTAFTERBOUNTY goal. Not implemented yet.")

    async def _handle_encounter_waypoint_foreach_goal(self, goal: GoalData):
        logger.info("Handling ENCOUNTER_WAYPOINT_FOREACH goal. Not implemented yet.")

    async def _handle_unimplemented_goal(self, goal: GoalData):
        goal_type = await goal.goal_type()
        logger.warning(f"No handler implemented for GoalType '{goal_type.name}'. Skipping.")

    # </editor-fold>

    # <editor-fold desc="Goal Matching Logic">
    async def _find_goal_by_text_matching(self, on_screen_text: str, goals: Dict[int, GoalData]) -> Tuple[
        int | None, GoalData | None]:
        if not on_screen_text:
            return None, None

        best_match_goal = None
        best_match_id = None
        highest_score = 0

        for goal_id, goal in goals.items():
            if await goal.goal_status():
                continue

            madlib_block = await goal.madlib_block()
            if not madlib_block:
                continue

            current_score = 0
            madlib_values = []
            entries = await madlib_block.entries()
            for entry in entries:
                value = await entry.maybe_data_str()
                if value:
                    translated = await Utils.translate_lang_key(self.client, value)
                    if '|' in translated:
                        madlib_values.append(translated.split('|')[-1])
                    else:
                        madlib_values.append(translated)

            for value in madlib_values:
                if value and value in on_screen_text:
                    current_score += 1

            logger.debug(f"Goal at {hex(goal.base_address)} has values {madlib_values} and scored {current_score}")

            if current_score > highest_score:
                highest_score = current_score
                best_match_goal = goal
                best_match_id = goal_id

        if highest_score >= 2:
            return best_match_id, best_match_goal

        return None, None

    async def _reconstruct_goal_text(self, goal: GoalData) -> str:
        """Preserved old method."""
        pass

    # </editor-fold>

    async def run(self):
        quest_manager = await self.client.quest_manager()
        character_registry = await self.client.character_registry()

        active_quest_id = await character_registry.active_quest_id()
        if not active_quest_id:
            logger.warning("No active quest is being tracked. Cannot proceed.")
            return

        all_quests = await quest_manager.quest_data()
        active_quest = all_quests.get(active_quest_id)

        if not active_quest:
            logger.error(f"Tracked quest ID {active_quest_id} not found in quest log.")
            return

        on_screen_text = await Utils.get_on_screen_goal_text(self.client)
        all_goals = await active_quest.goal_data()
        identified_goal_id, identified_goal = await self._find_goal_by_text_matching(on_screen_text, all_goals)

        # Initial check for blocking UI before starting the main logic
        zone_before_action = await self.client.zone_name()
        await self._handle_spiral_door(await identified_goal.goal_destination_zone() if identified_goal else "")
        await self._handle_sigil_entry()
        await self._handle_dialogue()
        if await self.client.zone_name() != zone_before_action:
            logger.info("UI handled at start of loop, restarting run.")
            return

        if not identified_goal:
            logger.error("Could not identify an active goal from on-screen text.")
            return

        logger.info(
            f"Currently tracking quest: '{await Utils.translate_lang_key(self.client, await active_quest.name_lang_key())}'")

        await self.log_full_quest_to_db(active_quest, active_quest_id)

        await self._print_quest_details(active_quest, active_quest_id, self.client)

        logger.info(f"Attempting to match on-screen text: '{on_screen_text}'")
        logger.success(f"Successfully matched text to Goal ID: {identified_goal_id} (Full 64-bit)")

        active_goal = identified_goal
        goal_type = await active_goal.goal_type()

        handler_method = self.goal_handlers.get(goal_type, self._handle_unimplemented_goal)

        logger.info(f"Processing active goal of type '{goal_type.name}'...")
        await handler_method(active_goal)

        # Final check after a handler has run
        await self._handle_spiral_door(await identified_goal.goal_destination_zone())
        await self._handle_sigil_entry()
        await self._handle_dialogue()


async def main():
    """Main execution function."""
    logger.info("Best Quest Started")
    handler = ClientHandler()
    db_logger = None
    try:
        client = handler.get_new_clients()[0]
        logger.success("Client found. Activating hooks...")
        await client.activate_hooks()

        db_logger = QuestDatabase()
        best_quest = BestQuest(client, [], db_logger)

        logger.info("Script running. Press SPACE to process the current quest, or '1' to exit.")
        while True:
            if keyboard.is_pressed('space'):
                await best_quest.run()
            if keyboard.is_pressed('1'):
                logger.info("Exit key pressed. Shutting down.")
                break

    except IndexError:
        logger.error("No Wizard101 client found.")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
    finally:
        if db_logger:
            db_logger.close()
        print("Closing client handler.")
        await handler.close()


if __name__ == "__main__":
    log_path = Path.cwd() / "BestQuestLogs.txt"
    logger.add(log_path, rotation="5 MB", level="DEBUG",
               format="{time} | {level: <8} | {name}:{function}:{line} - {message}")
    asyncio.run(main())