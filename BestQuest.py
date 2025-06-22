import inspect
import re
import time
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
    spiral_door_title_path, npc_range_path, popup_msgtext_path, dungeon_warning_path, spiral_door_exit_path, \
    decline_quest_path, dialog_text_path
from utils import get_window_from_path, is_visible_by_path, click_window_by_path


class PlayerState(Enum):
    FREE = "free"
    LOADING = "loading"
    COMBAT = "combat"
    DIALOGUE = "dialogue"
    FORCED_ANIMATION = "forced_animation"


class PlayerStateManager:
    def __init__(self, client: Client):
        self.client = client

    async def read_dialogue_text(self) -> str:
        try:
            dialogue_window = await get_window_from_path(self.client.root_window, dialog_text_path)
            text = await dialogue_window.maybe_text()
            return text if text else ""
        except Exception:
            return ""

    async def is_in_loading(self) -> bool:
        return await self.client.is_loading()

    async def is_in_combat(self) -> bool:
        return await self.client.in_battle()

    async def is_in_dialogue(self) -> bool:
        return await is_visible_by_path(self.client, advance_dialog_path)

    async def has_dialogue_text(self) -> bool:
        dialogue_text = await self.read_dialogue_text()
        return dialogue_text != ""

    async def get_current_state(self) -> PlayerState:
        if await self.is_in_loading():
            return PlayerState.LOADING
        if await self.is_in_combat():
            return PlayerState.COMBAT
        if await self.is_in_dialogue():
            return PlayerState.DIALOGUE
        if await self.has_dialogue_text():
            return PlayerState.FORCED_ANIMATION
        return PlayerState.FREE

    async def is_free(self) -> bool:
        current_state = await self.get_current_state()
        return current_state == PlayerState.FREE

    async def wait_for_free_state(self, timeout: float = None):
        import time
        start_time = time.time()
        
        while not await self.is_free():
            if timeout and (time.time() - start_time) > timeout:
                break
            await asyncio.sleep(0.1)

    async def handle_dialogue_safely(self) -> bool:
        if not await self.is_in_dialogue():
            return False

        try:
            # Check if this is a quest-related dialogue
            dialogue_text = await self.read_dialogue_text()
            
            # If dialogue contains quest-related keywords, we might want to accept
            quest_keywords = ["quest", "task", "help", "find", "collect", "defeat"]
            should_accept = any(keyword in dialogue_text.lower() for keyword in quest_keywords)
            
            if should_accept:
                # Accept the quest by clicking the right button (advance_dialog_path)
                logger.info("Accepting dialogue/quest")
                while await is_visible_by_path(self.client, advance_dialog_path):
                    await click_window_by_path(self.client, advance_dialog_path)
                    await asyncio.sleep(0.5)
            else:
                # Decline or exit dialogue by clicking the left button if available
                if await is_visible_by_path(self.client, decline_quest_path):
                    logger.info("Declining dialogue/quest")
                    await click_window_by_path(self.client, decline_quest_path)
                    await asyncio.sleep(0.5)
                else:
                    # Just advance through if no decline option
                    logger.info("Advancing through dialogue")
                    while await is_visible_by_path(self.client, advance_dialog_path):
                        await click_window_by_path(self.client, advance_dialog_path)
                        await asyncio.sleep(0.5)

            
            return True
        except Exception as e:
            logger.error(f"Error handling dialogue: {e}")
            return False


class Utils:
    # <editor-fold desc="Utility Functions">
    @staticmethod
    async def translate_lang_key(client: Client, lang_key: str) -> str:
        if not lang_key:
            return ""
        try:
            return await client.cache_handler.get_langcode_name(lang_key)
        except Exception as e:
            logger.error(f"[UTILS] Error translating lang key '{lang_key}': {e}", exc_info=True)
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
        except Exception as e:
            logger.error(f"[UTILS] Error reading quest text: {e}", exc_info=True)
            quest = ""
        return quest

    @staticmethod
    async def read_spiral_door_title(client: Client) -> str:
        try:
            title_text_path = await get_window_from_path(client.root_window, spiral_door_title_path)
            title = await title_text_path.maybe_text()
        except Exception as e:
            logger.error(f"[UTILS] Error reading spiral door title: {e}", exc_info=True)
            title = ""
        return title

    @staticmethod
    async def read_popup_text(p: Client) -> str:
        try:
            popup_text_path = await get_window_from_path(p.root_window, popup_msgtext_path)
            txtmsg = await popup_text_path.maybe_text()
        except Exception as e:
            logger.error(f"[UTILS] Error reading popup text: {e}", exc_info=True)
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
        self.state_manager = PlayerStateManager(client)
        self.last_sigil_exit_time = 0 # Track when we last exited a sigil
        self.sigil_grace_period = 5 # seconds to avoid re-entering immediately
        self.last_npc_dialogue_handled_time = 0.0
        self.npc_dialogue_cooldown = 5.0 # seconds to ignore new NPC interaction pop-ups
        
        # Quest/Goal change tracking
        self.current_quest_id = None
        self.current_goal_id = None
        self.current_goal_type = None

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

        # Add complete quest inspection for research
        logger.warning("[QUEST_DETAILS] Performing complete quest object inspection for research...")
        await self._inspect_object_completely(quest, f"QuestData_Details_{quest_id}", 0)

        quest_goals = await quest.goal_data()
        print("  Goals:")
        if not quest_goals:
            print("    (No goals found for this quest)")
        else:
            for goal_id, goal in quest_goals.items():
                display_goal_id = goal_id & 0xFFFFFFFF
                print(f"    - Goal ID: {display_goal_id} (Full: {goal_id})")
                await self._print_goal_details(goal, indent=6)
                
                # Add complete goal inspection for research
                logger.warning(f"[QUEST_DETAILS] Performing complete goal object inspection for goal {goal_id}...")
                await self._inspect_object_completely(goal, f"GoalData_Details_{goal_id}", 0)

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
            # Deep ClientTagList inspection
            logger.warning(f"[GOAL_DETAILS] Performing complete ClientTagList inspection...")
            await self._inspect_object_completely(client_tags, f"ClientTagList_GoalDetails", indent // 2)
            
        madlib = await goal.madlib_block()
        if madlib:
            await self._print_madlib_block(madlib, indent + 2)
            # Deep MadlibBlock inspection  
            logger.warning(f"[GOAL_DETAILS] Performing complete MadlibBlock inspection...")
            await self._inspect_object_completely(madlib, f"MadlibBlock_GoalDetails", indent // 2)

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
            final_sub_quest_info_string = await Utils.translate_lang_key(self.client, sub_quest_info_string) if sub_quest_info_string else None
            print(f"{indent_str}  - Identifier: {identifier}")  # identifier is a field name, not a lang key
            print(f"{indent_str}    Final Value: {final_sub_quest_info_string or 'Empty'}")

    # </editor-fold>

    # <editor-fold desc="Action Handlers">

    async def _handle_dialogue(self) -> bool:
        logger.debug("[DIALOGUE] Starting dialogue handling")
        
        # Small delay to catch any dialogue that might be appearing
        await asyncio.sleep(0.2)

        current_time = time.time()

        # Always apply NPC dialogue cooldown if an interaction was just handled,
        # regardless of zone comparison for the *current* goal.
        # This prevents immediate re-engagement with NPCs after a successful dialogue.
        if current_time - self.last_npc_dialogue_handled_time < self.npc_dialogue_cooldown:
            logger.debug(
                f"Skipping NPC dialogue handling due to cooldown. Time remaining: {self.npc_dialogue_cooldown - (current_time - self.last_npc_dialogue_handled_time):.2f}s")
            return False  # Indicate that we are intentionally skipping this interaction

        # Check for sigil entry dialog first
        if await is_visible_by_path(self.client, npc_range_path):
            popup_text = await Utils.read_popup_text(self.client)
            if "to enter" in popup_text.lower():
                logger.warning("Sigil dialog detected - handling sigil entry...")
                handled_sigil = await self._handle_sigil_entry()
                if handled_sigil:
                    self.last_npc_dialogue_handled_time = time.time()  # Update timestamp after successful sigil handling
                return handled_sigil

        # Handle initial NPC interaction pop-up (pressing 'X')
        # This is the prompt to initiate dialogue with an NPC
        if await is_visible_by_path(self.client, popup_title_path):
            logger.warning("Initial NPC interaction pop-up detected. Pressing 'X' to engage.")
            await self.client.send_key(Keycode.X, 0.1)
            await asyncio.sleep(1.0)
            # After pressing X, it's very likely to go into dialogue.
            # We will update last_npc_dialogue_handled_time upon successful dialogue handling.

        # Now check for actual dialogue being present (the larger dialogue window)
        if await self.state_manager.is_in_dialogue():
            logger.warning("Dialogue detected - handling safely...")
            
            # Check for quest changes before dialogue handling
            await self._check_quest_goal_changes("before_dialogue_handling")
            
            handled = await self.state_manager.handle_dialogue_safely()
            if handled:
                logger.success("Dialogue handled successfully.")
                self.last_npc_dialogue_handled_time = time.time()  # Update timestamp after successful dialogue
                
                # Check for quest changes after dialogue handling
                if await self._check_quest_goal_changes("after_dialogue_handling"):
                    logger.warning("[DIALOGUE] Quest/goal changes detected after dialogue handling")
                
                return True

        logger.debug("[DIALOGUE] No dialogue to handle")
        return False

    async def _handle_sigil_entry(self) -> bool:
        # Check if the sigil UI is even visible
        if not await is_visible_by_path(self.client, npc_range_path):
            return False

        # Read popup text to determine context
        popup_text = await Utils.read_popup_text(self.client)
        if "to enter" not in popup_text.lower():
            # Not a sigil entry dialog, so don't handle here
            return False

        logger.warning("Dungeon sigil entry dialog detected.")

        # --- NEW LOGIC: Prevent immediate re-entry after recent exit ---
        current_time = asyncio.get_event_loop().time()
        if current_time - self.last_sigil_exit_time < self.sigil_grace_period:
            # Check if player has moved far enough from where they exited
            player_pos = await self.client.body.position()
            # You would need to store the exit position from the sigil
            # For now, let's assume if it's within the grace period, we just skip re-entry
            # A more robust solution would store the exit location and check distance from it.
            logger.info(f"Within sigil grace period ({self.sigil_grace_period}s). Skipping re-entry attempt.")
            return False  # Indicate that we saw the UI but chose not to act

        # --- Your Proposed Radius Check (incorporating quest goal context) ---
        quest_manager = await self.client.quest_manager()
        character_registry = await self.client.character_registry()
        active_quest_id = await character_registry.active_quest_id()

        if active_quest_id:
            all_quests = await quest_manager.quest_data()
            active_quest = all_quests.get(active_quest_id)
            if active_quest:
                on_screen_text = await Utils.get_on_screen_goal_text(self.client)
                all_goals = await active_quest.goal_data()
                identified_goal_id, identified_goal = await self._find_goal_by_text_matching(on_screen_text, all_goals)

                if identified_goal:
                    quest_target_pos = await self.client.quest_position.position()  # This is the main quest position
                    player_pos = await self.client.body.position()

                    # Define a "near sigil" radius - needs tuning
                    # This could be the player's interaction range or a bit larger
                    sigil_interaction_radius = 500  # Example value, adjust as needed

                    distance_to_quest_target = ((player_pos.x - quest_target_pos.x) ** 2 + 
                                               (player_pos.y - quest_target_pos.y) ** 2) ** 0.5

                    # Check if the quest goal requires entering a sigil (e.g., goal_type, or specific madlib text)
                    # For simplicity, let's assume if the player is far from the target, and we are at a sigil UI, we should enter.
                    # Or, more precisely, if the QUEST TARGET is still *inside* the dungeon the sigil leads to.
                    # This might require pre-mapping zones to their sigils.

                    # A more direct check: if the *current goal's destination zone* is different from the current zone, AND the quest target
                    # is "close enough" to the sigil UI, then it's likely we need to enter.
                    goal_dest_zone = await identified_goal.goal_destination_zone()
                    current_zone = await self.client.zone_name()

                    # If goal destination zone is different from current zone, we likely need to enter
                    # AND the quest target is within a reasonable distance to the sigil (which is where the player is).
                    # This assumes quest_position points to something inside the sigil when you need to enter.
                    if goal_dest_zone and goal_dest_zone != current_zone:
                        logger.info(
                            f"Current goal destination zone ('{goal_dest_zone}') differs from current zone ('{current_zone}').")
                        # Here, you might also want to check if quest_target_pos is within the known bounds of the sigil itself
                        # but for now, rely on the simple distance to player
                        # A more advanced check: if the target_pos is in a known "dungeon zone" and player is outside
                        pass  # Proceed to enter sigil logic below
                    else:
                        logger.warning(
                            f"Sigil UI detected, but current goal destination ('{goal_dest_zone}') is same as current zone ('{current_zone}'). Skipping re-entry.")
                        return False  # Don't enter if we're already in the target zone for the goal
                else:
                    logger.warning("No identified active goal, skipping sigil re-entry logic.")
                    return False
            else:
                logger.warning("No active quest found, skipping sigil re-entry logic.")
                return False

        logger.info("Attempting to enter sigil...")
        await self.client.send_key(Keycode.X, 0.1)
        await asyncio.sleep(1.0)  # Give it a moment for the warning/loading screen

        if await is_visible_by_path(self.client, dungeon_warning_path):
            logger.info("Confirming dungeon entry...")
            await click_window_by_path(self.client, dungeon_warning_path)
            await asyncio.sleep(0.5)

        logger.info("Waiting for zone change after entering sigil...")
        zone_before_loading = await self.client.zone_name()

        # Wait for the loading screen to appear and then disappear
        start_wait_time = asyncio.get_event_loop().time()
        while not await self.client.is_loading():
            if asyncio.get_event_loop().time() - start_wait_time > 20:  # Timeout for loading screen to appear
                logger.warning("Loading screen did not appear after sigil entry attempt. Assume failed or already in.")
                return False
            await asyncio.sleep(0.1)

        while await self.client.is_loading():
            await asyncio.sleep(0.1)

        # After loading, check if the zone actually changed
        zone_after_loading = await self.client.zone_name()
        if zone_after_loading != zone_before_loading:
            logger.success(f"Entered dungeon: Zone changed from '{zone_before_loading}' to '{zone_after_loading}'.")
            # Store the current time as the last sigil exit time to prevent immediate re-entry if we exit soon
            self.last_sigil_exit_time = asyncio.get_event_loop().time()
            # Also store current position to check distance moved if grace period is active
            self.last_sigil_exit_pos = await self.client.body.position()
            return True
        else:
            logger.warning(
                "Sigil entry attempt completed, but zone did not change. Player might already be in dungeon or entry failed.")
            return False

    async def _cycle_new_portal(self, location_name: str):
        logger.warning(f"Advanced portal logic for location '{location_name}' is not yet implemented.")
        pass

    async def _handle_spiral_door(self, destination_zone: str) -> bool:
        if not await is_visible_by_path(self.client, spiral_door_teleport_path):
            return False
        ''' HANDEL "WAIT TRY AGIAN IN A SECOND WIZARD"
-- [MessageBoxModalWindow] Window
--- [messageBoxBG] Window
---- [Top] ControlSprite
---- [Bottom] ControlSprite
---- [Left] ControlSprite
---- [Right] ControlSprite
---- [TopLeft] ControlSprite
---- [TopRight] ControlSprite
---- [BottomLeft] ControlSprite
---- [TopLeft] ControlSprite
---- [messageBoxLayout] WindowLayout
----- [TitleCtrl] ControlText
----- [MsgCtrl] ControlText
----- [AdjustmentWindow] Window
------ [RetryBtn] ControlButton
------ [CancelBtn] ControlButton'''
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
        
        # Wait additional time for any post-teleport dialogue to appear
        await asyncio.sleep(1.5)
        logger.success("World travel complete.")
        return True

    # </editor-fold>

    # <editor-fold desc="Player State Helpers">
    async def _wait_for_free_state(self, timeout: float = 10.0) -> bool:
        await self.state_manager.wait_for_free_state(timeout)
        return await self.state_manager.is_free()

    async def _check_and_handle_player_state(self) -> bool:
        current_state = await self.state_manager.get_current_state()
        
        if current_state == PlayerState.DIALOGUE:
            logger.info(f"Player in dialogue state - handling...")
            return await self.state_manager.handle_dialogue_safely()
        elif current_state == PlayerState.LOADING:
            logger.info("Player in loading state - waiting...")
            await self.state_manager.wait_for_free_state(timeout=30.0)
            return True
        elif current_state == PlayerState.COMBAT:
            logger.info("Player in combat state - waiting...")
            await self.state_manager.wait_for_free_state(timeout=60.0)
            return True
        elif current_state == PlayerState.FORCED_ANIMATION:
            logger.info("Player in forced animation - waiting...")
            await self.state_manager.wait_for_free_state(timeout=15.0)
            return True
        
        return current_state == PlayerState.FREE

    async def _wait_for_combat_start(self, timeout: float = 10.0) -> bool:
        import time
        start_time = time.time()
        
        logger.info(f"Waiting for player to enter combat (timeout: {timeout}s)...")
        while time.time() - start_time < timeout:
            if await self.state_manager.is_in_combat():
                logger.success("Player entered combat!")
                return True
            await asyncio.sleep(0.1)
        
        logger.warning(f"Player did not enter combat within {timeout} seconds.")
        return False

    # </editor-fold>

    # <editor-fold desc="Movement Logic">
    async def _travel_to_goal_location(self, goal: GoalData):
        destination_zone = await goal.goal_destination_zone()
        max_failed_attempts = 10
        failed_attempts = 0
        # Get the actual goal ID from the quest system for proper tracking
        quest_manager = await self.client.quest_manager()
        character_registry = await self.client.character_registry()
        active_quest_id = await character_registry.active_quest_id()
        initial_goal_id = None
        if active_quest_id:
            all_quests = await quest_manager.quest_data()
            active_quest = all_quests.get(active_quest_id)
            if active_quest:
                all_goals = await active_quest.goal_data()
                for goal_id, quest_goal in all_goals.items():
                    if quest_goal == goal:
                        initial_goal_id = goal_id
                        break
        player_radius_offset = 1  # Start with default radius
        
        # Initialize position tracking for progress detection
        position_before_action = await self.client.body.position()
        
        # Track if we just switched worlds to avoid unnecessary UI handling
        initial_world = Utils.get_world_from_zone(await self.client.zone_name())
        just_switched_worlds = False

        while failed_attempts < max_failed_attempts:
            # Check for quest/goal changes at the start of each travel loop
            if await self._check_quest_goal_changes(f"travel_loop_start_attempt_{failed_attempts + 1}"):
                logger.warning("[TRAVEL] Quest/goal changes detected in travel loop, exiting travel")
                break
            
            current_zone = await self.client.zone_name()
            if not current_zone:
                await asyncio.sleep(0.5)
                continue

            logger.info(
                f"Travel Loop | Attempt [{failed_attempts + 1}/{max_failed_attempts}] | Destination: '{destination_zone}' | Current: '{current_zone}' | Radius Offset: {player_radius_offset}")

            # Check if we've reached the destination zone
            if current_zone == destination_zone:
                logger.success("Player is in the correct zone.")
                break

            # Check if goal has changed (quest progression) by re-checking active quest
            if initial_goal_id:
                current_quest_id = await character_registry.active_quest_id()
                if current_quest_id != active_quest_id:
                    logger.info("Active quest has changed during travel, exiting travel loop.")
                    break
                
                # Also check if the current goal is still active by re-matching on-screen text
                current_on_screen_text = await Utils.get_on_screen_goal_text(self.client)
                if current_on_screen_text:
                    current_quests = await quest_manager.quest_data()
                    current_active_quest = current_quests.get(current_quest_id)
                    if current_active_quest:
                        current_goals = await current_active_quest.goal_data()
                        current_identified_goal_id, current_identified_goal = await self._find_goal_by_text_matching(current_on_screen_text, current_goals)
                        if current_identified_goal_id and current_identified_goal_id != initial_goal_id:
                            logger.info(f"Goal has changed from {initial_goal_id} to {current_identified_goal_id}, exiting travel loop.")
                            break

            zone_before_action = current_zone
            position_before_action = await self.client.body.position()

            # Check if we just switched worlds in this loop iteration
            current_world = Utils.get_world_from_zone(current_zone)
            if current_world != initial_world:
                just_switched_worlds = True
                initial_world = current_world
                logger.info(f"Detected world switch to '{current_world}'. Skipping initial UI handling to avoid reopening spiral door.")
            else:
                just_switched_worlds = False
            
            # FIRST: Check player state and handle any blocking conditions
            if not just_switched_worlds:
                # Wait for player to be in a free state before proceeding
                await self._wait_for_free_state(timeout=10.0)
                
                # Check and handle current player state
                state_handled = await self._check_and_handle_player_state()
                
                # Handle UI elements
                dialogue_handled = await self._handle_dialogue()
                ui_handled = dialogue_handled or await self._handle_spiral_door(destination_zone)
                if not ui_handled:
                    ui_handled = await self._handle_sigil_entry()
                
                # Check again for dialogue after UI interactions if no sigil was handled
                if not dialogue_handled:
                    await self._handle_dialogue()
            else:
                # If we just switched worlds, we still need to track ui_handled for logic flow
                ui_handled = False
                logger.info("Skipped UI handling due to recent world switch. Proceeding directly to teleportation.")

            # Check for quest/goal changes after UI handling
            if await self._check_quest_goal_changes(f"travel_after_ui_attempt_{failed_attempts + 1}"):
                logger.warning("[TRAVEL] Quest/goal changes detected after UI handling, exiting travel")
                break
            
            # Check if UI interaction caused a zone change
            current_zone_after_ui = await self.client.zone_name()
            if current_zone_after_ui != zone_before_action:
                logger.success("UI interaction resulted in a zone change. Re-evaluating position.")
                # Reset radius offset after successful zone change
                player_radius_offset = 1
                # Update world tracking since we changed zones
                initial_world = Utils.get_world_from_zone(current_zone_after_ui)
                continue

            # If no UI was available or handled (or we skipped UI due to world switch), attempt WorldsCollideTP
            if not ui_handled:
                logger.warning("No interactive zoning UI available. Using WorldsCollideTP to move closer...")
                try:
                    await WorldsCollideTP(self.client, player_radius_offset=player_radius_offset)
                    await asyncio.sleep(2.0)
                    
                    # Check for quest/goal changes after teleportation
                    if await self._check_quest_goal_changes(f"travel_after_teleport_attempt_{failed_attempts + 1}"):
                        logger.warning("[TRAVEL] Quest/goal changes detected after teleportation, exiting travel")
                        break
                    
                    # IMMEDIATELY check for dialogue and UI that might appear after teleportation
                    await self._handle_dialogue()
                    
                    # Check for quest/goal changes after post-teleport dialogue
                    if await self._check_quest_goal_changes(f"travel_after_post_teleport_dialogue_attempt_{failed_attempts + 1}"):
                        logger.warning("[TRAVEL] Quest/goal changes detected after post-teleport dialogue, exiting travel")
                        break
                    
                    # Check if dialogue handling caused a zone change
                    zone_after_dialogue = await self.client.zone_name()
                    if zone_after_dialogue != zone_before_action:
                        logger.success("Post-teleportation dialogue handling resulted in zone change.")
                        player_radius_offset = 1
                        # Update world tracking since we changed zones
                        initial_world = Utils.get_world_from_zone(zone_after_dialogue)
                        continue
                    
                    # Also check for other UI elements that might have appeared
                    ui_appeared = await self._handle_spiral_door(destination_zone)
                    if not ui_appeared:
                        ui_appeared = await self._handle_sigil_entry()
                    
                    if ui_appeared:
                        logger.info("UI elements appeared after teleportation, will re-evaluate in next loop.")
                        # Update world tracking in case UI caused world change
                        post_ui_zone = await self.client.zone_name()
                        initial_world = Utils.get_world_from_zone(post_ui_zone)
                        continue
                    
                except Exception as e:
                    logger.error(f"An error occurred during WorldsCollideTP: {e}", exc_info=True)
                    failed_attempts += 1
                    # Increase radius offset to push away from collision issues
                    player_radius_offset = min(player_radius_offset + 0.2, 1.5)
                    continue

                # Check if WorldsCollideTP made progress (zone change or significant position change)
                zone_after_tp = await self.client.zone_name()
                position_after_tp = await self.client.body.position()
                
                # Calculate distance moved
                distance_moved = ((position_after_tp.x - position_before_action.x) ** 2 + 
                                (position_after_tp.y - position_before_action.y) ** 2) ** 0.5
                
                zone_changed = zone_after_tp != zone_before_action
                significant_movement = distance_moved > 200  # Minimum progress threshold
                
                if zone_changed or significant_movement:
                    if zone_changed:
                        logger.success(f"Zone change detected: {zone_before_action} → {zone_after_tp}")
                    else:
                        logger.success(f"Significant movement detected: {distance_moved:.1f} units")
                    
                    # Reset radius offset after successful movement
                    player_radius_offset = 1
                    # Update world tracking in case we moved to a new world
                    initial_world = Utils.get_world_from_zone(zone_after_tp)
                    # Update position tracking for next iteration
                    position_before_action = position_after_tp
                else:
                    logger.error(f"No progress made in this travel attempt (moved {distance_moved:.1f} units, zone unchanged).")
                    failed_attempts += 1
                    # Increase radius offset to avoid getting stuck in same location
                    player_radius_offset = min(player_radius_offset + 0.2, 1.5)
        else:
            logger.error(
                f"Failed to reach destination zone '{destination_zone}' after {max_failed_attempts} failed attempts.")
            return

        logger.info("Performing final teleport to precise waypoint location...")
        try:
            await WorldsCollideTP(self.client, player_radius_offset=player_radius_offset)
            await asyncio.sleep(1.0)
            # Final UI check after arriving at the exact spot
            await self._handle_dialogue()
            await self._handle_sigil_entry()  # Check for sigils at final location too
            logger.success("Arrived at final quest location.")
        except Exception as e:
            logger.error(f"Final teleportation failed: {e}", exc_info=True)

    # </editor-fold>

    # <editor-fold desc="Goal Handlers">
    async def _handle_waypoint_goal(self, goal: GoalData):
        try:
            logger.info("Handling WAYPOINT goal")
            await self._travel_to_goal_location(goal)
        except Exception as e:
            logger.error(f"[HANDLER] Error in waypoint goal handler: {e}", exc_info=True)

    async def _handle_persona_goal(self, goal: GoalData):
        try:
            logger.info("Handling PERSONA goal.")
            
            # Check for changes before travel
            if await self._check_quest_goal_changes("persona_before_travel"):
                logger.warning("[HANDLER] Quest/goal changes detected before persona travel, aborting handler")
                return
            
            await self._travel_to_goal_location(goal)
            
            # Check for changes after travel
            if await self._check_quest_goal_changes("persona_after_travel"):
                logger.warning("[HANDLER] Quest/goal changes detected after persona travel, aborting handler")
                return
                
            await self._handle_dialogue()
            
            # Check for changes after dialogue
            await self._check_quest_goal_changes("persona_after_dialogue")
            
        except Exception as e:
            logger.error(f"[HANDLER] Error in persona goal handler: {e}", exc_info=True)

    async def _handle_usage_goal(self, goal: GoalData):
        try:
            logger.info("Handling USAGE goal.")
            
            # Check for changes before travel
            if await self._check_quest_goal_changes("usage_before_travel"):
                logger.warning("[HANDLER] Quest/goal changes detected before usage travel, aborting handler")
                return
            
            await self._travel_to_goal_location(goal)
            
            # Check for changes after travel
            await self._check_quest_goal_changes("usage_after_travel")
            
        except Exception as e:
            logger.error(f"[HANDLER] Error in usage goal handler: {e}", exc_info=True)

    async def _handle_bounty_goal(self, goal: GoalData):
        logger.info("Handling BOUNTY goal.")
        await self._travel_to_goal_location(goal)
        logger.info("This is a Defeat quest. Waiting for player to enter combat...")
        await self._wait_for_combat_start()

    async def _handle_bountycollect_goal(self, goal: GoalData):
        logger.info("Handling BOUNTYCOLLECT goal.")
        await self._travel_to_goal_location(goal)
        logger.info("This is a Defeat and Collect quest. Waiting for player to enter combat...")
        await self._wait_for_combat_start()

    async def _handle_scavenge_goal(self, goal: GoalData):
        logger.info("Handling SCAVENGE goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_scavengefake_goal(self, goal: GoalData):
        logger.info("Handling SCAVENGEFAKE goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_achieverank_goal(self, goal: GoalData):
        logger.info("Handling ACHIEVERANK goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_completequest_goal(self, goal: GoalData):
        logger.info("Handling COMPLETEQUEST goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_sociarank_goal(self, goal: GoalData):
        logger.info("Handling SOCIARANK goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_sociacurrency_goal(self, goal: GoalData):
        logger.info("Handling SOCIACURRENCY goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_sociaminigame_goal(self, goal: GoalData):
        logger.info("Handling SOCIAMINIGAME goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_sociagiveitem_goal(self, goal: GoalData):
        logger.info("Handling SOCIAGIVEITEM goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_sociagetitem_goal(self, goal: GoalData):
        logger.info("Handling SOCIAGETITEM goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_collectafterbounty_goal(self, goal: GoalData):
        logger.info("Handling COLLECTAFTERBOUNTY goal.")
        await self._travel_to_goal_location(goal)

    async def _handle_encounter_waypoint_foreach_goal(self, goal: GoalData):
        logger.info("Handling ENCOUNTER_WAYPOINT_FOREACH goal.")
        await self._travel_to_goal_location(goal)

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

    # <editor-fold desc="Object Inspection Utilities">
    async def _inspect_object_completely(self, obj, obj_name: str, indent: int = 0):
        """Comprehensively inspect any object and log ALL available data"""
        indent_str = ' ' * indent
        logger.warning(f"{indent_str}[OBJECT_INSPECTION] ===== {obj_name} COMPLETE INSPECTION =====")
        
        if obj is None:
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] {obj_name} is None")
            return
        
        try:
            # Log basic object info
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Object Type: {type(obj)}")
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Object Class: {obj.__class__}")
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Base Address: {hex(obj.base_address) if hasattr(obj, 'base_address') else 'N/A'}")
            
            # Log object hierarchy
            mro = getattr(obj.__class__, '__mro__', [])
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Class Hierarchy: {[cls.__name__ for cls in mro]}")
            
            # Get all attributes and methods
            all_attrs = dir(obj)
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Total Attributes/Methods: {len(all_attrs)}")
            
            # Separate methods from properties
            methods = []
            properties = []
            
            for attr_name in all_attrs:
                if attr_name.startswith('_'):
                    continue  # Skip private/protected
                
                try:
                    attr = getattr(obj, attr_name)
                    if callable(attr):
                        methods.append(attr_name)
                    else:
                        properties.append(attr_name)
                except Exception:
                    logger.warning(f"{indent_str}[OBJECT_INSPECTION] Could not access attribute: {attr_name}")
            
            # Log properties first
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] --- PROPERTIES ({len(properties)}) ---")
            for prop_name in sorted(properties):
                try:
                    value = getattr(obj, prop_name)
                    logger.warning(f"{indent_str}[OBJECT_INSPECTION] Property {prop_name}: {value} (type: {type(value)})")
                except Exception as e:
                    logger.warning(f"{indent_str}[OBJECT_INSPECTION] Property {prop_name}: <Error: {e}>")
            
            # Log and call all async methods
            logger.warning(f"{indent_str}[OBJECT_INSPECTION] --- ASYNC METHODS ({len(methods)}) ---")
            for method_name in sorted(methods):
                try:
                    method = getattr(obj, method_name)
                    if inspect.iscoroutinefunction(method):
                        # Try to call the async method
                        try:
                            result = await method()
                            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Method {method_name}(): {result} (type: {type(result)})")
                            
                            # If result is an object, inspect it briefly
                            if hasattr(result, '__dict__') or hasattr(result, 'base_address'):
                                logger.warning(f"{indent_str}[OBJECT_INSPECTION]   -> {method_name}() returned object: {type(result)}")
                        except Exception as e:
                            logger.warning(f"{indent_str}[OBJECT_INSPECTION] Method {method_name}(): <Error: {e}>")
                    else:
                        logger.warning(f"{indent_str}[OBJECT_INSPECTION] Method {method_name}: <Not async or not callable>")
                except Exception as e:
                    logger.warning(f"{indent_str}[OBJECT_INSPECTION] Could not inspect method {method_name}: {e}")
            
            # Check for __dict__ and __slots__
            if hasattr(obj, '__dict__'):
                logger.warning(f"{indent_str}[OBJECT_INSPECTION] --- __dict__ CONTENTS ---")
                for key, value in obj.__dict__.items():
                    logger.warning(f"{indent_str}[OBJECT_INSPECTION] __dict__.{key}: {value} (type: {type(value)})")
            
            if hasattr(obj, '__slots__'):
                logger.warning(f"{indent_str}[OBJECT_INSPECTION] --- __slots__ CONTENTS ---")
                logger.warning(f"{indent_str}[OBJECT_INSPECTION] __slots__: {obj.__slots__}")
                
        except Exception as e:
            logger.error(f"{indent_str}[OBJECT_INSPECTION] Error during complete inspection: {e}", exc_info=True)
        
        logger.warning(f"{indent_str}[OBJECT_INSPECTION] ===== END {obj_name} INSPECTION =====")
    # </editor-fold>

    # <editor-fold desc="Quest/Goal Change Detection">
    async def _check_quest_goal_changes(self, context: str = "") -> bool:
        """
        Check if the current quest ID, goal ID, or goal type has changed.
        Returns True if any changes were detected, False otherwise.
        """
        try:
            logger.debug(f"[CHANGE_DETECTION] Checking quest/goal changes - Context: {context}")
            
            # Get current quest manager state
            quest_manager = await self.client.quest_manager()
            character_registry = await self.client.character_registry()
            
            current_quest_id = await character_registry.active_quest_id()
            
            if not current_quest_id:
                logger.warning(f"[CHANGE_DETECTION] No active quest ID found - Context: {context}")
                if self.current_quest_id is not None:
                    logger.error(f"[CHANGE_DETECTION] Quest ID changed from {self.current_quest_id} to None!")
                    self.current_quest_id = None
                    self.current_goal_id = None
                    self.current_goal_type = None
                    return True
                return False
            
            # Get current goal information
            all_quests = await quest_manager.quest_data()
            active_quest = all_quests.get(current_quest_id)
            
            current_goal_id = None
            current_goal_type = None
            
            if active_quest:
                on_screen_text = await Utils.get_on_screen_goal_text(self.client)
                all_goals = await active_quest.goal_data()
                current_goal_id, current_goal = await self._find_goal_by_text_matching(on_screen_text, all_goals)
                
                if current_goal:
                    current_goal_type = await current_goal.goal_type()
            
            # Check for changes
            quest_id_changed = self.current_quest_id != current_quest_id
            goal_id_changed = self.current_goal_id != current_goal_id
            goal_type_changed = self.current_goal_type != current_goal_type
            
            any_changes = quest_id_changed or goal_id_changed or goal_type_changed
            
            # Log current state
            logger.info(f"[CHANGE_DETECTION] Context: {context}")
            logger.info(f"[CHANGE_DETECTION] Current State -> Quest ID: {current_quest_id}, Goal ID: {current_goal_id}, Goal Type: {current_goal_type.name if current_goal_type else 'None'}")
            logger.info(f"[CHANGE_DETECTION] Previous State -> Quest ID: {self.current_quest_id}, Goal ID: {self.current_goal_id}, Goal Type: {self.current_goal_type.name if self.current_goal_type else 'None'}")
            
            if any_changes:
                logger.warning(f"[CHANGE_DETECTION] CHANGES DETECTED - Context: {context}")
                
                if quest_id_changed:
                    logger.warning(f"[CHANGE_DETECTION] Quest ID changed: {self.current_quest_id} -> {current_quest_id}")
                    if active_quest:
                        quest_name = await Utils.translate_lang_key(self.client, await active_quest.name_lang_key())
                        logger.warning(f"[CHANGE_DETECTION] New quest name: {quest_name}")
                
                if goal_id_changed:
                    logger.warning(f"[CHANGE_DETECTION] Goal ID changed: {self.current_goal_id} -> {current_goal_id}")
                
                if goal_type_changed:
                    old_type_name = self.current_goal_type.name if self.current_goal_type else 'None'
                    new_type_name = current_goal_type.name if current_goal_type else 'None'
                    logger.warning(f"[CHANGE_DETECTION] Goal Type changed: {old_type_name} -> {new_type_name}")
                
                # Update stored values
                self.current_quest_id = current_quest_id
                self.current_goal_id = current_goal_id
                self.current_goal_type = current_goal_type
                
                # Log the re-evaluation details
                await self._log_quest_reevaluation(active_quest, current_quest_id, current_goal_id, current_goal)
                
                return True
            else:
                logger.debug(f"[CHANGE_DETECTION] No changes detected - Context: {context}")
                return False
                
        except Exception as e:
            logger.error(f"[CHANGE_DETECTION] Error checking quest/goal changes - Context: {context}: {e}", exc_info=True)
            return False

    async def _log_quest_reevaluation(self, active_quest, quest_id, goal_id, goal):
        """Log detailed information about quest re-evaluation"""
        try:
            logger.warning("[RE_EVALUATION] ===== QUEST/GOAL RE-EVALUATION =====")
            if active_quest:
                quest_name = await Utils.translate_lang_key(self.client, await active_quest.name_lang_key())
                logger.warning(f"[RE_EVALUATION] New Quest: {quest_name} (ID: {quest_id})")
                
                # Complete QuestData inspection
                await self._inspect_object_completely(active_quest, f"QuestData_{quest_id}", 2)
                
                if goal:
                    goal_name = await Utils.translate_lang_key(self.client, await goal.name_lang_key())
                    goal_type = await goal.goal_type()
                    goal_destination = await goal.goal_destination_zone()
                    goal_status = await goal.goal_status()
                    
                    logger.warning(f"[RE_EVALUATION] New Goal: {goal_name} (ID: {goal_id})")
                    logger.warning(f"[RE_EVALUATION] Goal Type: {goal_type.name}")
                    logger.warning(f"[RE_EVALUATION] Goal Destination: {goal_destination}")
                    logger.warning(f"[RE_EVALUATION] Goal Status: {'Complete' if goal_status else 'Incomplete'}")
                    
                    # Log handler that would be used
                    handler_method = self.goal_handlers.get(goal_type, self._handle_unimplemented_goal)
                    handler_name = handler_method.__name__ if handler_method else "unknown"
                    logger.warning(f"[RE_EVALUATION] Handler Method: {handler_name}")
                    
                    # Complete GoalData inspection
                    await self._inspect_object_completely(goal, f"GoalData_{goal_id}", 2)
                    
                    # Deep madlib inspection
                    madlib_block = await goal.madlib_block()
                    if madlib_block:
                        logger.warning("[RE_EVALUATION] Madlib Basic Entries:")
                        entries = await madlib_block.entries()
                        for i, entry in enumerate(entries):
                            identifier = await entry.identifier()
                            data_str = await entry.maybe_data_str()
                            # identifier is a field name (like "NAME", "LOCATION"), not a lang key - don't translate it
                            # data_str is the actual lang key that should be translated
                            translated_data = await Utils.translate_lang_key(self.client, data_str) if data_str else "None"
                            logger.warning(f"[RE_EVALUATION]   - {identifier}: {translated_data}")
                        
                        # Complete MadlibBlock inspection
                        await self._inspect_object_completely(madlib_block, f"MadlibBlock_{goal_id}", 2)
                        
                        # Inspect each MadlibEntry
                        for i, entry in enumerate(entries):
                            await self._inspect_object_completely(entry, f"MadlibEntry_{i}_{goal_id}", 4)
                    
                    # Inspect ClientTagList if available
                    client_tags = await goal.client_tag_list()
                    if client_tags:
                        await self._inspect_object_completely(client_tags, f"ClientTagList_{goal_id}", 2)
                
            logger.warning("[RE_EVALUATION] =====================================")
        except Exception as e:
            logger.error(f"[RE_EVALUATION] Error logging quest re-evaluation: {e}", exc_info=True)
    # </editor-fold>

    async def run(self):
        # Check for quest/goal changes at the start of run cycle
        logger.info("[RUN] Starting quest processing cycle")
        if await self._check_quest_goal_changes("run_start"):
            logger.warning("[RUN] Quest/goal changes detected at start, restarting run cycle")
            return
        
        # Handle any dialogue that might be on screen from previous quest completion
        logger.debug("Checking for dialogue at start of quest processing cycle...")
        await self._handle_dialogue()
        
        # Check for changes after dialogue handling
        if await self._check_quest_goal_changes("after_initial_dialogue"):
            logger.warning("[RUN] Quest/goal changes detected after initial dialogue, restarting run cycle")
            return
        
        # Wait for player to be in a free state before quest detection
        logger.debug("Waiting for free state before quest detection...")
        await self._wait_for_free_state(timeout=10.0)
        
        # Handle any remaining player state issues
        await self._check_and_handle_player_state()
        
        # Check for changes after state handling
        if await self._check_quest_goal_changes("after_state_handling"):
            logger.warning("[RUN] Quest/goal changes detected after state handling, restarting run cycle")
            return
        
        try:
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
        except Exception as e:
            logger.error(f"[RUN] Error getting quest manager data: {e}", exc_info=True)
            return

        # Initial check for blocking UI before starting the main logic
        zone_before_action = await self.client.zone_name()
        position_before_action = await self.client.body.position()
        
        # Wait for player to be free before starting quest logic
        await self._wait_for_free_state(timeout=15.0)
        
        # Check and handle any blocking states
        await self._check_and_handle_player_state()
        
        # Check for changes after initial setup
        if await self._check_quest_goal_changes("after_initial_setup"):
            logger.warning("[RUN] Quest/goal changes detected after initial setup, restarting run cycle")
            return
        
        if identified_goal:
            ui_handled = await self._handle_spiral_door(await identified_goal.goal_destination_zone())
            if not ui_handled:
                ui_handled = await self._handle_sigil_entry()
            # Always check for dialogue after any teleportation or UI interaction
            await self._handle_dialogue()
            
            # Check for changes after UI handling
            if await self._check_quest_goal_changes("after_ui_handling"):
                logger.warning("[RUN] Quest/goal changes detected after UI handling, restarting run cycle")
                return
            
            if await self.client.zone_name() != zone_before_action:
                logger.info("UI handled at start of loop, restarting run.")
                return
        else:
            # Still handle dialogue even if no goal identified
            await self._handle_dialogue()

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
        # input("Quest Auditor -> Press Enter to after looking at the type of goal.")

        # Check for changes before executing handler
        if await self._check_quest_goal_changes("before_handler_execution"):
            logger.warning("[RUN] Quest/goal changes detected before handler execution, restarting run cycle")
            return

        await handler_method(active_goal)

        # Check for changes after handler execution
        if await self._check_quest_goal_changes("after_handler_execution"):
            logger.warning("[RUN] Quest/goal changes detected after handler execution, restarting run cycle")
            return

        # Final check after a handler has run
        if identified_goal:
            ui_handled = await self._handle_spiral_door(await identified_goal.goal_destination_zone())
            if not ui_handled:
                ui_handled = await self._handle_sigil_entry()
        
        # Check for changes after final UI handling
        if await self._check_quest_goal_changes("after_final_ui"):
            logger.warning("[RUN] Quest/goal changes detected after final UI handling, restarting run cycle")
            return
        
        # Final state check and dialogue handling
        await self._check_and_handle_player_state()
        await self._handle_dialogue()
        
        # Final check for changes
        await self._check_quest_goal_changes("run_end")


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

        logger.info("Script running. Press NINE to process the current quest, or END to exit.")
        while True:
            # if keyboard.is_pressed('9'):
            await best_quest.run()
            logger.info("Quest processing complete. Restarting quest processing loop...")
            await asyncio.sleep(2.0)  # Brief pause before reprocessing
            # if keyboard.is_pressed('end'):
            #     logger.info("Exit key pressed. Shutting down.")
            #     break

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