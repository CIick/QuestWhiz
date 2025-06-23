import asyncio
import time
import traceback
import math
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field

from wizwalker import XYZ, Client, Keycode, MemoryReadError
from wizwalker.memory import DynamicClientObject
from wizwalker.file_readers.wad import Wad
from thefuzz import fuzz

from teleport_math import parse_nav_data, calc_chunks, calc_Distance
from WorldsCollide import WorldsCollideTP
from sprinty_client import SprintyClient
from utils import is_free, get_window_from_path, is_visible_by_path
from paths import npc_range_path

@dataclass
class CollectedEntity:
    """Track collected entities with location and timestamp"""
    location: XYZ
    timestamp: float
    entity_name: str

@dataclass
class QuestProgressState:
    """Track quest progress to avoid restarting collection from beginning"""
    quest_id: str
    processed_chunks: Set[int] = field(default_factory=set)
    collected_entities: Dict[str, CollectedEntity] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)

# Global state management to persist across BestQuest calls
_persistent_quest_states: Dict[str, QuestProgressState] = {}
_current_quest_handler: Optional['UsageQuestHandler'] = None

class UsageQuestHandler:
    """Handler for usage quest collection with intelligent entity detection and safe collection"""
    
    def __init__(self, client: Client, clients: List[Client] = None, quest_id: str = None):
        self.client = client
        self.clients = clients or [client]
        self.quest_id = quest_id
        self.quest_progress_state: Optional[QuestProgressState] = None
        self.collected_entities: Dict[str, CollectedEntity] = {}
        self.processed_chunks: Set[int] = set()
        self.entities_to_skip = [
            'Basic Positional', 'WispHealth', 'WispMana', 'KT_WispHealth', 
            'KT_WispMana', 'WispGold', 'DuelCircle', 'Player Object', 
            'SkeletonKeySigilArt', 'Basic Ambient', 'TeleportPad'
        ]
        self.collection_cooldown = 30.0  # seconds (reduced from 60 for faster respawn)
        self.underground_offset = -550.0
        self.approach_increment = 0.5  # half player height
        self.max_approach_attempts = 10
        self.entity_distance = 3147.0  # render distance for chunking
        
        # Initialize or restore persistent state
        self._initialize_quest_state()
        
    def _initialize_quest_state(self):
        """Initialize or restore quest progress state"""
        global _persistent_quest_states
        
        if self.quest_id and self.quest_id in _persistent_quest_states:
            # Restore existing state
            self.quest_progress_state = _persistent_quest_states[self.quest_id]
            self.collected_entities = self.quest_progress_state.collected_entities
            self.processed_chunks = self.quest_progress_state.processed_chunks
            print(f"Restored quest state: {len(self.processed_chunks)} chunks processed, {len(self.collected_entities)} entities collected")
        elif self.quest_id:
            # Create new state
            self.quest_progress_state = QuestProgressState(quest_id=self.quest_id)
            _persistent_quest_states[self.quest_id] = self.quest_progress_state
            print(f"Created new quest state for quest ID: {self.quest_id}")
    
    def _save_quest_state(self):
        """Save current progress to persistent state"""
        if self.quest_progress_state:
            self.quest_progress_state.collected_entities = self.collected_entities
            self.quest_progress_state.processed_chunks = self.processed_chunks
            self.quest_progress_state.last_updated = time.time()
    
    async def load_wad(self, zone_name: str) -> Wad:
        """Load WAD file for the current zone"""
        return Wad.from_game_data(zone_name.replace("/", "-"))
    
    async def get_zone_chunks(self) -> List[XYZ]:
        """Get zone chunks for systematic area coverage"""
        try:
            wad = await self.load_wad(await self.client.zone_name())
            nav_data = await wad.get_file("zone.nav")
            vertices, _ = parse_nav_data(nav_data)
            chunks = calc_chunks(vertices, self.entity_distance)
            return chunks
        except Exception as e:
            print(f"Error getting zone chunks: {e}")
            return []
    
    def _get_optimized_chunk_order(self, chunks: List[XYZ], player_pos: XYZ) -> List[Tuple[int, XYZ]]:
        """Get chunks ordered by distance from player for more efficient pathing"""
        indexed_chunks = [(i, chunk) for i, chunk in enumerate(chunks)]
        
        # Filter out already processed chunks
        remaining_chunks = [
            (i, chunk) for i, chunk in indexed_chunks 
            if i not in self.processed_chunks
        ]
        
        # Sort by distance from player
        def distance_to_player(chunk_data):
            _, chunk = chunk_data
            dx = chunk.x - player_pos.x
            dy = chunk.y - player_pos.y
            return math.sqrt(dx*dx + dy*dy)
        
        remaining_chunks.sort(key=distance_to_player)
        
        print(f"Optimized chunk order: {len(remaining_chunks)} remaining chunks out of {len(chunks)} total")
        return remaining_chunks
    
    async def get_quest_item_name(self) -> str:
        """Extract quest item name from quest text"""
        try:
            quest_name_path = ["WorldView", "windowHUD", "QuestHelperHud", "ElementWindow", "", "txtGoalName"]
            quest_window = await get_window_from_path(self.client.root_window, quest_name_path)
            quest_text = await quest_window.maybe_text()
            
            # Parse quest text like "Collect Cog in Triton Avenue (0 of 3)"
            import re
            match = re.search(r'collect\s+(.*?)\s+in\s+', quest_text.lower())
            if match:
                return match.group(1).strip()
            return ""
        except Exception:
            return ""
    
    async def is_position_safe(self, position: XYZ, safe_distance: float = 1000.0) -> bool:
        """Check if position is safe from mobs"""
        try:
            sprinter = SprintyClient(self.client)
            mobs = await sprinter.get_mobs()
            
            for mob in mobs:
                mob_pos = await mob.location()
                if calc_Distance(mob_pos, position) < safe_distance:
                    return False
            return True
        except Exception:
            return True  # Default to safe if check fails
    
    async def is_entity_recently_collected(self, entity: DynamicClientObject) -> bool:
        """Check if entity was recently collected (within cooldown period)"""
        try:
            entity_location = await entity.location()
            current_time = time.time()
            
            # Check against all recently collected entities
            for entity_id, collected in self.collected_entities.items():
                if calc_Distance(entity_location, collected.location) < 50.0:  # Close enough to be same entity
                    if current_time - collected.timestamp < self.collection_cooldown:
                        return True
                    else:
                        # Remove expired entries
                        del self.collected_entities[entity_id]
            return False
        except Exception:
            return False
    
    async def mark_entity_collected(self, entity: DynamicClientObject, entity_name: str):
        """Mark entity as collected with timestamp and save state"""
        try:
            entity_location = await entity.location()
            entity_id = f"{entity_name}_{entity_location.x}_{entity_location.y}"
            self.collected_entities[entity_id] = CollectedEntity(
                location=entity_location,
                timestamp=time.time(),
                entity_name=entity_name
            )
            # Immediately save state when entity is collected
            self._save_quest_state()
            print(f"Marked entity as collected: {entity_name} at {entity_location}")
        except Exception as e:
            print(f"Error marking entity as collected: {e}")
    
    async def clean_expired_collections(self):
        """Remove expired collection records"""
        current_time = time.time()
        expired_ids = []
        
        for entity_id, collected in self.collected_entities.items():
            if current_time - collected.timestamp >= self.collection_cooldown:
                expired_ids.append(entity_id)
        
        for entity_id in expired_ids:
            del self.collected_entities[entity_id]
    
    async def match_entity_icon(self, entity: DynamicClientObject, quest_item_name: str) -> bool:
        """Check if entity icon matches quest icon (1:1 match)"""
        try:
            # Get entity icon
            entity_template = await entity.object_template()
            entity_icon = await entity_template.icon()
            
            # TODO: Compare with quest icon - this would require extracting quest icon
            # For now, return False and rely on other matching methods
            return False
        except Exception:
            return False
    
    async def match_entity_by_display_name(self, entity: DynamicClientObject, quest_item_name: str) -> int:
        """Match entity by display name using fuzzy matching"""
        try:
            entity_template = await entity.object_template()
            display_name_code = await entity_template.display_name()
            display_name = await self.client.cache_handler.get_langcode_name(display_name_code)
            
            if display_name:
                match_score = fuzz.token_sort_ratio(display_name.lower(), quest_item_name.lower())
                return match_score
        except Exception:
            pass
        return 0
    
    async def match_entity_by_object_name(self, entity: DynamicClientObject, quest_item_name: str) -> int:
        """Match entity by object name with processing"""
        try:
            entity_template = await entity.object_template()
            object_name = str(await entity_template.object_name())
            
            if object_name in self.entities_to_skip:
                return 0
            
            # Process object name like in auto_collect_rewrite
            name_list = object_name.split('_')
            if len(name_list) == 1:
                name_list = object_name.split('-')
            
            if len(name_list) > 1:
                edited_name = ''.join(name_list[1:])
                # Strip digits and underscores
                cleaned_name = ''.join([i for i in edited_name if not i.isdigit()])
                cleaned_name = cleaned_name.replace("_", "")
                
                match_score = fuzz.ratio(cleaned_name.lower(), quest_item_name.lower())
                return match_score
        except Exception:
            pass
        return 0
    
    async def approach_entity_from_below(self, target_location: XYZ) -> bool:
        """Approach entity from below in small increments"""
        try:
            # Start below target
            current_z = target_location.z - (self.approach_increment * self.max_approach_attempts)
            approach_location = XYZ(target_location.x, target_location.y, current_z)
            
            for attempt in range(self.max_approach_attempts):
                # Move up incrementally
                approach_location.z += self.approach_increment
                
                # Check if position is safe
                if not await self.is_position_safe(approach_location):
                    continue
                
                # Teleport to approach position
                await self.client.teleport(approach_location)
                await asyncio.sleep(0.2)
                
                # Check if we're in range for collection
                if await is_visible_by_path(self.client, npc_range_path):
                    return True
            
            return False
        except Exception as e:
            print(f"Error approaching entity: {e}")
            return False
    
    async def collect_entity(self, entity: DynamicClientObject, entity_name: str) -> bool:
        """Attempt to collect entity safely"""
        try:
            entity_location = await entity.location()
            
            # Check if recently collected
            if await self.is_entity_recently_collected(entity):
                return False
            
            # Check if position is safe
            if not await self.is_position_safe(entity_location):
                return False
            
            # Store safe location to return to
            safe_location = await self.client.body.position()
            
            # Approach from below
            if not await self.approach_entity_from_below(entity_location):
                # Fallback to collision-aware teleport
                try:
                    await WorldsCollideTP(self.client, entity_location)
                except Exception as e:
                    print(f"WorldsCollideTP failed: {e}")
                    return False
            
            await asyncio.sleep(0.3)
            
            # Check if collection UI is visible
            if await is_visible_by_path(self.client, npc_range_path):
                # Attempt collection
                for attempt in range(5):
                    await asyncio.gather(*[client.send_key(Keycode.X, 0.1) for client in self.clients])
                    await asyncio.sleep(0.1)
                
                # Wait for collection to complete
                while not await is_free(self.client) or await self.client.in_battle():
                    await asyncio.sleep(0.1)
                
                # Mark as collected
                await self.mark_entity_collected(entity, entity_name)
                
                # Return to safe location
                await self.client.teleport(safe_location)
                return True
            
            # Return to safe location if collection failed
            await self.client.teleport(safe_location)
            return False
            
        except Exception as e:
            print(f"Error collecting entity: {e}")
            return False
    
    async def find_and_collect_in_chunk(self, chunk_location: XYZ, quest_item_name: str) -> bool:
        """Search for and collect entities in a specific chunk"""
        try:
            # Move underground to chunk location
            underground_location = XYZ(chunk_location.x, chunk_location.y, chunk_location.z + self.underground_offset)
            await self.client.teleport(underground_location)
            await asyncio.sleep(0.2)
            
            # Get entities in this area
            entities = await self.client.get_base_entity_list()
            
            # Try icon matching first (highest priority)
            for entity in entities:
                try:
                    if await self.match_entity_icon(entity, quest_item_name):
                        if await self.collect_entity(entity, quest_item_name):
                            return True
                except Exception:
                    continue
            
            # Try display name matching (high priority)
            best_display_match = None
            best_display_score = 0
            
            for entity in entities:
                try:
                    score = await self.match_entity_by_display_name(entity, quest_item_name)
                    if score > 80 and score > best_display_score:  # High threshold for display name
                        best_display_score = score
                        best_display_match = entity
                except Exception:
                    continue
            
            if best_display_match:
                if await self.collect_entity(best_display_match, quest_item_name):
                    return True
            
            # Try object name matching (fallback)
            best_object_match = None
            best_object_score = 0
            
            for entity in entities:
                try:
                    score = await self.match_entity_by_object_name(entity, quest_item_name)
                    if score > 50 and score > best_object_score:  # Lower threshold for object name
                        best_object_score = score
                        best_object_match = entity
                except Exception:
                    continue
            
            if best_object_match:
                if await self.collect_entity(best_object_match, quest_item_name):
                    return True
            
            return False
            
        except Exception as e:
            print(f"Error processing chunk: {e}")
            return False
    
    async def verify_zone_location(self, expected_zone: str = None) -> bool:
        """Verify client is in the correct zone for the quest"""
        try:
            current_zone = await self.client.zone_name()
            
            if expected_zone:
                return current_zone.lower() == expected_zone.lower()
            
            # If no expected zone provided, assume we're in the right place
            return True
        except Exception:
            return False
    
    async def process_usage_quest(self, expected_zone: str = None) -> bool:
        """Main method to process usage quest collection"""
        try:
            # Verify zone location
            if not await self.verify_zone_location(expected_zone):
                print(f"Client not in correct zone. Expected: {expected_zone}, Current: {await self.client.zone_name()}")
                return False
            
            # Get quest item name
            quest_item_name = await self.get_quest_item_name()
            if not quest_item_name:
                print("Could not determine quest item name")
                return False
            
            print(f"Looking for quest item: {quest_item_name}")
            
            # Clean up expired collection records
            await self.clean_expired_collections()
            
            # Get zone chunks
            chunks = await self.get_zone_chunks()
            if not chunks:
                print("No chunks found for zone")
                return False
            
            # Get player position for optimized chunk ordering
            player_pos = await self.client.body.position()
            
            # Get optimized chunk order (skips already processed chunks)
            remaining_chunks = self._get_optimized_chunk_order(chunks, player_pos)
            
            if not remaining_chunks:
                print("All chunks already processed for this quest")
                return False
            
            print(f"Processing {len(remaining_chunks)} remaining chunks (out of {len(chunks)} total)")
            
            # Process each remaining chunk
            for chunk_index, (original_index, chunk) in enumerate(remaining_chunks):
                print(f"Processing chunk {chunk_index+1}/{len(remaining_chunks)} (original index: {original_index+1})")
                
                # Wait for client to be free
                while not await is_free(self.client) or await self.client.in_battle():
                    await asyncio.sleep(0.1)
                
                # Search and collect in this chunk
                collection_success = await self.find_and_collect_in_chunk(chunk, quest_item_name)
                
                # Mark chunk as processed regardless of collection success
                self.processed_chunks.add(original_index)
                self._save_quest_state()
                
                if collection_success:
                    print(f"Successfully collected item in chunk {original_index+1}")
                    return True
                
                # Small delay between chunks
                await asyncio.sleep(0.1)
            
            print("No collectible items found in any chunk")
            return False
            
        except Exception as e:
            print(f"Error processing usage quest: {e}")
            traceback.print_exc()
            return False

def _get_quest_id_from_client(client: Client) -> Optional[str]:
    """Extract quest ID from client for state tracking"""
    try:
        # Try to get a unique identifier for the current quest
        # This is a simplified approach - in practice, you might want to get
        # the actual quest ID from the quest manager
        return f"quest_{id(client)}_{int(time.time() / 3600)}"  # Rough hour-based grouping
    except Exception:
        return None

def get_persistent_handler(client: Client, clients: List[Client] = None, quest_id: str = None) -> UsageQuestHandler:
    """Get or create persistent handler to maintain state across calls"""
    global _current_quest_handler
    
    # Generate quest ID if not provided
    if not quest_id:
        quest_id = _get_quest_id_from_client(client)
    
    # Create new handler if none exists or quest changed
    if (_current_quest_handler is None or 
        _current_quest_handler.quest_id != quest_id or
        _current_quest_handler.client != client):
        
        print(f"Creating new persistent handler for quest: {quest_id}")
        _current_quest_handler = UsageQuestHandler(client, clients, quest_id)
    else:
        print(f"Reusing persistent handler for quest: {quest_id}")
        # Update clients list in case it changed
        _current_quest_handler.clients = clients or [client]
    
    return _current_quest_handler

def clear_quest_state(quest_id: str = None):
    """Clear persistent state for a specific quest or all quests"""
    global _persistent_quest_states, _current_quest_handler
    
    if quest_id:
        if quest_id in _persistent_quest_states:
            del _persistent_quest_states[quest_id]
            print(f"Cleared state for quest: {quest_id}")
    else:
        _persistent_quest_states.clear()
        _current_quest_handler = None
        print("Cleared all quest states")

# Convenience function for external use
async def collect_usage_quest_items(client: Client, clients: List[Client] = None, expected_zone: str = None) -> bool:
    """
    Main function to collect usage quest items with persistent state management
    
    Args:
        client: Primary client to use for collection
        clients: List of all clients (for multi-client collection)
        expected_zone: Expected zone name for verification
    
    Returns:
        bool: True if collection was successful, False otherwise
    """
    handler = get_persistent_handler(client, clients)
    return await handler.process_usage_quest(expected_zone)