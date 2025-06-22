import asyncio
import inspect
import math
import os
import shutil
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Coroutine, Sequence, Union, List
from katsuba.op import *
from katsuba.wad import Archive
from katsuba.utils import string_id
import json
# Added import for keyboard listening
import keyboard
from loguru import logger
import numpy as np
import matplotlib
from memobj import WindowsProcess
from wizwalker.memory import DynamicClientObject, ActorBody
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union, nearest_points

from utils import is_free

# DEV flag to control destructive actions like deleting directories
DEV_MODE = False

# Use 'Agg' backend for saving plots to file without GUI issues
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly

from wizwalker import Client, ClientHandler, XYZ
from collision import get_collision_data, CollisionWorld, ProxyType, get_nif_from_wad, find_nif_wad_candidates, get_entity_collision_shape, get_cache_directory, load_cached_wcp_collision, save_wcp_collision_cache
from collision_math import toCubeVertices, transformCube


# Global tracking for dynamic collision zones discovered through rubber-band failures
_dynamic_collision_zones = []  # List of {"position": XYZ, "radius": float, "zone_name": str}


# <editor-fold desc="Dynamic Collision Zone Management">

async def _add_or_expand_dynamic_collision_zone(failed_position: XYZ, zone_name: str, player_radius: float, client: Client):
    """
    Add a new dynamic collision zone or expand an existing one at the failed teleport location.
    
    Args:
        failed_position: Where the teleport was attempted but rubber-banded
        zone_name: Current zone name for tracking
        player_radius: Current player radius for expansion calculations
        client: Game client for saving to cache
    """
    global _dynamic_collision_zones
    
    # Check if we already have a collision zone near this position (within 100 units)
    existing_zone = None
    for zone in _dynamic_collision_zones:
        if zone["zone_name"] == zone_name:
            distance = ((zone["position"].x - failed_position.x) ** 2 + 
                       (zone["position"].y - failed_position.y) ** 2) ** 0.5
            if distance < 100:  # Consider zones within 100 units as the same failure area
                existing_zone = zone
                break
    
    if existing_zone:
        # Expand existing zone by player radius
        existing_zone["radius"] += player_radius
        logger.warning(f"Expanded dynamic collision zone at {existing_zone['position']} to radius {existing_zone['radius']:.1f}")
    else:
        # Create new collision zone starting with base radius
        initial_radius = 50.0  # Base size for newly discovered collision
        new_zone = {
            "position": failed_position,
            "radius": initial_radius,
            "zone_name": zone_name
        }
        _dynamic_collision_zones.append(new_zone)
        logger.warning(f"Added new dynamic collision zone at {failed_position} with radius {initial_radius}")
    
    # Save updated dynamic collision zones to file
    await _save_dynamic_collision_zones(client, zone_name)


def _get_dynamic_collision_polygons(zone_name: str) -> List[Polygon]:
    """
    Get collision polygons for all dynamic collision zones in the current zone.
    
    Args:
        zone_name: Current zone name
        
    Returns:
        List of Polygon objects representing dynamic collision zones
    """
    polygons = []
    for zone in _dynamic_collision_zones:
        if zone["zone_name"] == zone_name:
            # Create circular collision polygon at the failed position
            collision_circle = Point(zone["position"].x, zone["position"].y).buffer(zone["radius"])
            polygons.append(collision_circle)
    
    if polygons:
        logger.info(f"Including {len(polygons)} dynamic collision zones in collision calculation")
    
    return polygons


def _clear_dynamic_collision_zones(zone_name: str = None):
    """
    Clear dynamic collision zones, optionally only for a specific zone.
    
    Args:
        zone_name: If provided, only clear zones for this zone. If None, clear all.
    """
    global _dynamic_collision_zones
    
    if zone_name:
        initial_count = len(_dynamic_collision_zones)
        _dynamic_collision_zones = [zone for zone in _dynamic_collision_zones if zone["zone_name"] != zone_name]
        cleared_count = initial_count - len(_dynamic_collision_zones)
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} dynamic collision zones for zone {zone_name}")
    else:
        cleared_count = len(_dynamic_collision_zones)
        _dynamic_collision_zones = []
        if cleared_count > 0:
            logger.info(f"Cleared all {cleared_count} dynamic collision zones")


async def _save_dynamic_collision_zones(client: Client, zone_name: str):
    """
    Save dynamic collision zones for a zone to a WCP file for persistence across sessions.
    
    Args:
        client: Game client for cache directory access
        zone_name: Zone name to save dynamic collision for
    """
    try:
        from collision import get_cache_directory
        
        cache_dir = await get_cache_directory(client)
        sane_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
        manual_collision_file = cache_dir / f"{sane_zone_name}_manual_collision.wcp"
        
        # Load existing data first if file exists
        existing_data = []
        if manual_collision_file.exists():
            try:
                with open(manual_collision_file, 'r') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Could not load existing dynamic collision data from {manual_collision_file}, starting fresh")
                existing_data = []
        
        # Get current dynamic collision zones for this zone
        current_zone_data = []
        for zone in _dynamic_collision_zones:
            if zone["zone_name"] == zone_name:
                current_zone_data.append({
                    "x": zone["position"].x,
                    "y": zone["position"].y, 
                    "z": zone["position"].z,
                    "radius": zone["radius"]
                })
        
        # Merge existing and current data, avoiding duplicates
        merged_data = existing_data.copy()
        for new_zone in current_zone_data:
            # Check if this zone position already exists in saved data
            duplicate_found = False
            for existing_zone in merged_data:
                distance = ((existing_zone["x"] - new_zone["x"]) ** 2 + 
                           (existing_zone["y"] - new_zone["y"]) ** 2) ** 0.5
                if distance < 50:  # Same threshold used for detection
                    # Update radius if the new one is larger
                    if new_zone["radius"] > existing_zone["radius"]:
                        existing_zone["radius"] = new_zone["radius"]
                    duplicate_found = True
                    break
            
            if not duplicate_found:
                merged_data.append(new_zone)
        
        if merged_data:
            with open(manual_collision_file, 'w') as f:
                json.dump(merged_data, f, indent=2)
            logger.info(f"Saved {len(merged_data)} dynamic collision zones to {manual_collision_file}")
        else:
            # Remove file if no zones to save
            if manual_collision_file.exists():
                manual_collision_file.unlink()
                logger.info(f"Removed empty dynamic collision file: {manual_collision_file}")
                
    except Exception as e:
        logger.error(f"Failed to save dynamic collision zones: {e}")


async def _load_dynamic_collision_zones(client: Client, zone_name: str):
    """
    Load previously saved dynamic collision zones for a zone from WCP file.
    
    Args:
        client: Game client for cache directory access
        zone_name: Zone name to load dynamic collision for
    """
    global _dynamic_collision_zones
    
    try:
        from collision import get_cache_directory
        
        cache_dir = await get_cache_directory(client)
        sane_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
        manual_collision_file = cache_dir / f"{sane_zone_name}_manual_collision.wcp"
        
        if not manual_collision_file.exists():
            return  # No saved dynamic collision data
        
        with open(manual_collision_file, 'r') as f:
            zone_data = json.load(f)
        
        # Load zones into memory, but only if they're not already present
        loaded_count = 0
        for zone_info in zone_data:
            position = XYZ(zone_info["x"], zone_info["y"], zone_info["z"])
            
            # Check if we already have a similar zone (avoid duplicates)
            exists = False
            for existing_zone in _dynamic_collision_zones:
                if (existing_zone["zone_name"] == zone_name and 
                    abs(existing_zone["position"].x - position.x) < 50 and
                    abs(existing_zone["position"].y - position.y) < 50):
                    exists = True
                    break
            
            if not exists:
                _dynamic_collision_zones.append({
                    "position": position,
                    "radius": zone_info["radius"],
                    "zone_name": zone_name
                })
                loaded_count += 1
        
        if loaded_count > 0:
            logger.info(f"Loaded {loaded_count} dynamic collision zones from {manual_collision_file}")
            
    except Exception as e:
        logger.error(f"Failed to load dynamic collision zones: {e}")


# <editor-fold desc="Refactored Helper Functions">

def filter_valid_polygons(shapes: List[Any]) -> List[Polygon]:
    """Filter out non-polygon geometries (like LineString) to prevent .exterior crashes."""
    valid_polygons = []
    for shape in shapes:
        if hasattr(shape, 'geom_type'):
            if shape.geom_type == 'Polygon':
                valid_polygons.append(shape)
            elif shape.geom_type == 'MultiPolygon':
                # Extract individual polygons from MultiPolygon
                for poly in shape.geoms:
                    if poly.geom_type == 'Polygon':
                        valid_polygons.append(poly)
                logger.debug(f"Expanded MultiPolygon into {len(shape.geoms)} individual polygons")
            else:
                logger.warning(f"Filtering out non-polygon geometry: {shape.geom_type}")
        else:
            logger.warning(f"Filtering out unknown geometry type: {type(shape)}")
    return valid_polygons


def generate_collision_plots(static_shapes: List[Polygon], entity_shapes: List[Polygon], 
                           player_pos: XYZ, target_pos: XYZ, expected_tp_pos: XYZ, 
                           zone_name: str, debug: bool = True) -> None:
    """
    Generate 3 collision visualization plots:
    1. Combined collision map (static + entities)
    2. Static collision only 
    3. Entity collision only
    """
    if not debug:
        logger.debug("Debug mode disabled, skipping collision plot generation")
        return
    
    try:
        # Create images directory
        images_dir = Path("images")
        images_dir.mkdir(exist_ok=True)
        
        # Generate safe zone name for filename
        safe_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # Filter out any invalid geometries
        static_shapes = filter_valid_polygons(static_shapes)
        entity_shapes = filter_valid_polygons(entity_shapes)
        
        if not static_shapes and not entity_shapes:
            logger.warning("No valid collision shapes to plot")
            return
        
        # Calculate bounds for all plots
        all_shapes = static_shapes + entity_shapes
        if all_shapes:
            all_bounds = [shape.bounds for shape in all_shapes]
            min_x = min(bounds[0] for bounds in all_bounds)
            min_y = min(bounds[1] for bounds in all_bounds) 
            max_x = max(bounds[2] for bounds in all_bounds)
            max_y = max(bounds[3] for bounds in all_bounds)
            
            # Expand bounds to include key positions
            positions_x = [player_pos.x, target_pos.x, expected_tp_pos.x]
            positions_y = [player_pos.y, target_pos.y, expected_tp_pos.y]
            
            min_x = min(min_x, min(positions_x) - 100)
            max_x = max(max_x, max(positions_x) + 100)
            min_y = min(min_y, min(positions_y) - 100)
            max_y = max(max_y, max(positions_y) + 100)
        else:
            # Fallback bounds based on positions only
            positions_x = [player_pos.x, target_pos.x, expected_tp_pos.x]
            positions_y = [player_pos.y, target_pos.y, expected_tp_pos.y]
            min_x, max_x = min(positions_x) - 500, max(positions_x) + 500
            min_y, max_y = min(positions_y) - 500, max(positions_y) + 500
        
        # Common plot setup function
        def setup_plot(ax, title: str):
            ax.set_xlim(min_x, max_x)
            ax.set_ylim(min_y, max_y)
            ax.set_aspect('equal')
            ax.grid(True, alpha=0.3)
            ax.set_title(f"{title}\n{zone_name}", fontsize=12)
            ax.set_xlabel("X Coordinate")
            ax.set_ylabel("Y Coordinate")
            
            # Add position markers
            # ax.plot(player_pos.x, player_pos.y, marker='*', color='green', markersize=15,
            #        label='Player Start', zorder=10)
            # ax.plot(target_pos.x, target_pos.y, marker='X', color='red', markersize=12,
            #        label='Quest Target', zorder=10)
            ax.plot(expected_tp_pos.x, expected_tp_pos.y, marker='o', color='blue', markersize=10, 
                   label='Expected TP', zorder=10)
            ax.legend(loc='upper right')
        
        # 1. Combined collision map
        fig, ax = plt.subplots(figsize=(12, 10))
        setup_plot(ax, "Combined Collision Map")
        
        # Plot static collision (blue)
        for shape in static_shapes:
            if hasattr(shape, 'exterior'):
                x, y = shape.exterior.xy
                ax.plot(x, y, color='blue', linewidth=1, alpha=0.7)
                ax.fill(x, y, color='blue', alpha=0.3)
        
        # Plot entity collision (red, with different styles for multi-polygon entities)
        multi_polygon_count = 0
        for shape in entity_shapes:
            if hasattr(shape, 'exterior'):
                x, y = shape.exterior.xy
                # Use slightly different colors to distinguish multi-polygon components
                color = 'red' if multi_polygon_count == 0 else 'darkred'
                alpha = 0.7 - (multi_polygon_count * 0.1)  # Vary transparency slightly
                ax.plot(x, y, color=color, linewidth=1, alpha=max(alpha, 0.3))
                ax.fill(x, y, color=color, alpha=max(0.3 - (multi_polygon_count * 0.05), 0.1))
                multi_polygon_count += 1
        
        # Add color legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color='blue', alpha=0.7, linewidth=3, label='Static Collision'),
            Line2D([0], [0], color='red', alpha=0.7, linewidth=3, label='Entity Collision (NIF-based)'),
            Line2D([0], [0], color='darkred', alpha=0.6, linewidth=2, label='Multi-part Entity Components')
        ]
        ax.legend(handles=legend_elements, loc='upper left')
        
        combined_file = images_dir / f"{safe_zone_name}_{timestamp}_combined_collision_map.png"
        plt.tight_layout()
        plt.savefig(combined_file, dpi=150, bbox_inches='tight')
        plt.close()
        logger.success(f"Saved combined collision map: {combined_file}")
        
        # 2. Static collision only
        fig, ax = plt.subplots(figsize=(12, 10))
        setup_plot(ax, "Static Collision Map")
        
        for shape in static_shapes:
            if hasattr(shape, 'exterior'):
                x, y = shape.exterior.xy
                ax.plot(x, y, color='blue', linewidth=1, alpha=0.8)
                ax.fill(x, y, color='blue', alpha=0.4)
        
        static_file = images_dir / f"{safe_zone_name}_{timestamp}_static_collision_map.png"
        plt.tight_layout()
        plt.savefig(static_file, dpi=150, bbox_inches='tight')
        plt.close()
        logger.success(f"Saved static collision map: {static_file}")
        
        # 3. Entity collision only
        fig, ax = plt.subplots(figsize=(12, 10))
        setup_plot(ax, "Entity Collision Map")
        
        # Enhanced visualization for entity collision plots
        multi_polygon_count = 0
        for shape in entity_shapes:
            if hasattr(shape, 'exterior'):
                x, y = shape.exterior.xy
                # Use different colors for multi-polygon components
                color = 'red' if multi_polygon_count == 0 else 'darkred'
                alpha = 0.8 - (multi_polygon_count * 0.1)
                ax.plot(x, y, color=color, linewidth=1, alpha=max(alpha, 0.4))
                ax.fill(x, y, color=color, alpha=max(0.4 - (multi_polygon_count * 0.05), 0.2))
                multi_polygon_count += 1
        
        entity_file = images_dir / f"{safe_zone_name}_{timestamp}_entity_collision_map.png"
        plt.tight_layout()
        plt.savefig(entity_file, dpi=150, bbox_inches='tight')
        plt.close()
        logger.success(f"Saved entity collision map: {entity_file}")
        
        # 4. Player area detail collision map
        _collision_around_player(
            static_shapes=static_shapes,
            entity_shapes=entity_shapes, 
            player_pos=player_pos,
            zone_name=zone_name,
            target_pos=target_pos,
            show_target=True,
            show_quest=True,
            debug=debug
        )
        
        logger.info(f"Generated collision plots for {len(static_shapes)} static and {len(entity_shapes)} entity shapes")
        
    except Exception as e:
        logger.error(f"Failed to generate collision plots: {e}")


def _collision_around_player(static_shapes: List[Polygon], entity_shapes: List[Polygon], 
                           player_pos: XYZ, zone_name: str, 
                           zoom_radius: float = 5000.0,
                           target_pos: XYZ = None, 
                           show_target: bool = True, 
                           show_quest: bool = True,
                           debug: bool = True) -> None:
    """
    Generate a detailed collision plot centered around the player position.
    Shows collision shapes within a specified radius for detailed analysis.
    
    Args:
        static_shapes: List of static collision polygons
        entity_shapes: List of entity collision polygons  
        player_pos: Player position (center of plot)
        zone_name: Zone name for filename
        zoom_radius: Radius around player to include (default 5000 units)
        target_pos: Optional quest target position
        show_target: Whether to show target marker
        show_quest: Whether to show quest-related markers
        debug: Whether to generate the plot (debug mode check)
    """
    if not debug:
        logger.debug("Debug mode disabled, skipping player area collision plot")
        return
    
    try:
        # Create images directory
        images_dir = Path("images")
        images_dir.mkdir(exist_ok=True)
        
        # Generate safe zone name for filename
        safe_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # Calculate bounds centered on player
        center_x, center_y = player_pos.x, player_pos.y
        min_x = center_x - zoom_radius
        max_x = center_x + zoom_radius
        min_y = center_y - zoom_radius
        max_y = center_y + zoom_radius
        
        # Filter shapes to only include those within or intersecting the zoom area
        from shapely.geometry import box
        zoom_box = box(min_x, min_y, max_x, max_y)
        
        # Filter collision shapes to zoom area
        visible_static = []
        visible_entity = []
        
        for shape in static_shapes:
            if hasattr(shape, 'intersects') and zoom_box.intersects(shape):
                visible_static.append(shape)
        
        for shape in entity_shapes:
            if hasattr(shape, 'intersects') and zoom_box.intersects(shape):
                visible_entity.append(shape)
        
        logger.debug(f"Player area plot: {len(visible_static)} static, {len(visible_entity)} entity shapes in {zoom_radius}-unit radius around player at ({player_pos.x:.1f}, {player_pos.y:.1f})")
        
        # Create the plot
        fig, ax = plt.subplots(figsize=(12, 12))
        
        # Set bounds and styling
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)
        ax.set_title(f"Player Area Collision Detail\n{zone_name} (Radius: {zoom_radius:.0f} units)", fontsize=14, fontweight='bold')
        ax.set_xlabel("X Coordinate")
        ax.set_ylabel("Y Coordinate")
        
        # Plot static collision shapes (blue)
        for shape in visible_static:
            if hasattr(shape, 'exterior'):
                x, y = shape.exterior.xy
                ax.plot(x, y, color='blue', linewidth=1.5, alpha=0.8)
                ax.fill(x, y, color='blue', alpha=0.3)
        
        # Plot entity collision shapes (red with multi-polygon support)
        multi_polygon_count = 0
        for shape in visible_entity:
            if hasattr(shape, 'exterior'):
                x, y = shape.exterior.xy
                # Use different shades for multi-polygon components
                color = 'red' if multi_polygon_count == 0 else 'darkred'
                alpha = 0.8 - (multi_polygon_count * 0.1)
                ax.plot(x, y, color=color, linewidth=1.5, alpha=max(alpha, 0.4))
                ax.fill(x, y, color=color, alpha=max(0.4 - (multi_polygon_count * 0.05), 0.15))
                multi_polygon_count += 1
        
        # Plot player position (distinctive green marker)
        ax.plot(player_pos.x, player_pos.y, marker='*', color='lime', markersize=20, 
               markeredgecolor='darkgreen', markeredgewidth=2, label='Player Position', zorder=10)
        
        # Optionally plot target position
        if show_target and target_pos:
            ax.plot(target_pos.x, target_pos.y, marker='X', color='orange', markersize=15,
                   markeredgecolor='darkorange', markeredgewidth=2, label='Quest Target', zorder=9)
        
        # Create legend
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], marker='*', color='lime', markersize=15, markeredgecolor='darkgreen', 
                   linestyle='None', label='Player Position'),
            Line2D([0], [0], color='blue', alpha=0.7, linewidth=3, label='Static Collision'),
            Line2D([0], [0], color='red', alpha=0.7, linewidth=3, label='Entity Collision (NIF-based)')
        ]
        
        if show_target and target_pos:
            legend_elements.append(
                Line2D([0], [0], marker='X', color='orange', markersize=12, markeredgecolor='darkorange',
                       linestyle='None', label='Quest Target')
            )
        
        if visible_entity and multi_polygon_count > 1:
            legend_elements.append(
                Line2D([0], [0], color='darkred', alpha=0.6, linewidth=2, label='Multi-part Entity Components')
            )
        
        ax.legend(handles=legend_elements, loc='upper right')
        
        # Add zoom radius indicator
        circle = plt.Circle((player_pos.x, player_pos.y), zoom_radius, fill=False, 
                           color='gray', linestyle='--', alpha=0.5, linewidth=1)
        ax.add_patch(circle)
        
        # Save the plot
        player_area_file = images_dir / f"{safe_zone_name}_{timestamp}_player_area_collision.png"
        plt.tight_layout()
        plt.savefig(player_area_file, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.success(f"Saved player area collision plot: {player_area_file}")
        
    except Exception as e:
        logger.error(f"Failed to generate player area collision plot: {e}")


async def _setup_export_paths(client: Client) -> tuple[Path, str]:
    """Sets up the directories and filenames for exporting collision data."""
    revision, zone_name = await get_revision_and_zone(client)
    sane_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")

    output_dir = Path("calculated_collisions") / revision
    output_dir.mkdir(parents=True, exist_ok=True)

    if DEV_MODE:
        logger.warning(f"DEV_MODE is ON. Deleting contents of {output_dir}...")
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    output_file_name = f"{sane_zone_name}_collision_polygons.wcp"
    output_file_path = output_dir / output_file_name
    logger.info(f"Collision data will be exported to: {output_file_path}")

    image_dir = Path("images")
    image_dir.mkdir(exist_ok=True)

    return output_file_path, sane_zone_name


async def _load_and_build_collision_geometry(client: Client, z_slice: float, debug: bool = False) -> tuple[
    CollisionWorld, List[Polygon], List[Polygon]]:
    """Loads raw collision data and builds 2D polygon shapes for static geometry."""
    
    # Try to load cached collision data first
    try:
        cache_dir = await get_cache_directory(client)
        zone_name = await client.zone_name()
        cached_polygons = load_cached_wcp_collision(cache_dir, zone_name)
        
        if cached_polygons:
            logger.info(f"Using cached collision data with {len(cached_polygons)} polygons")
            # Still need to load raw data for mesh shapes and world object info
            raw = await get_collision_data(client)
            world = CollisionWorld()
            world.load(raw)
            mesh_shapes = build_mesh_shapes(world, z_slice)
            return world, cached_polygons, mesh_shapes
        else:
            logger.info("No cached collision data found, generating from raw data...")
            
    except Exception as e:
        logger.warning(f"Failed to load cached collision data: {e}")
        logger.info("Falling back to raw collision data generation...")
    
    # Load and process raw collision data
    raw = await get_collision_data(client)
    world = CollisionWorld()
    world.load(raw)

    if debug:
        print("Static collision objects in this zone:")
        for obj in world.objects:
            print(f"  {obj.proxy.name:8s} '{obj.name}' at {obj.location} params={obj.params}")
        print("─" * 60)

    coll_shapes = build_collision_shapes(world, z_slice, debug=debug)
    mesh_shapes = build_mesh_shapes(world, z_slice)
    
    # Save the generated collision data to cache
    try:
        cache_dir = await get_cache_directory(client)
        zone_name = await client.zone_name()
        save_wcp_collision_cache(cache_dir, zone_name, coll_shapes)
    except Exception as e:
        logger.warning(f"Failed to save collision data to cache: {e}")
    
    return world, coll_shapes, mesh_shapes


def _op_to_dict(type_list, v):
    """Convert LazyObjects and LazyLists to regular Python objects for JSON serialization"""
    if isinstance(v, LazyObject):
        result = {}

        # Add the type hash as $__type (this is the key part!)
        if hasattr(v, 'type_hash'):
            result["$__type"] = v.type_hash

        # Add all the object's properties
        for k, e in v.items(type_list):
            result[k] = _op_to_dict(type_list, e)

        return result
    elif isinstance(v, LazyList):
        return [_op_to_dict(type_list, e) for e in v]
    elif isinstance(v, bytes):
        try:
            return v.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return v.decode('latin-1')
            except UnicodeDecodeError:
                import base64
                return {"__bytes__": base64.b64encode(v).decode('ascii')}
    elif hasattr(v, '__class__') and v.__class__.__name__ == 'Color':
        return {
            "__type__": "Color",
            "value": str(v)
        }
    return v


async def _debug_write_entity_json(entity_name: str, serializable_data: dict) -> None:
    """Debug function to write entity data to JSON files"""
    entities_dir = Path.cwd() / "entities"
    entities_dir.mkdir(exist_ok=True)

    json_file = entities_dir / f"{entity_name}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(serializable_data, f, indent=2, ensure_ascii=False)

    logger.info(f"[DEV_MODE] Saved deserialized data for {entity_name} to {json_file}")


async def _log_asset_to_file(entity_name: str, asset_name: str, zone_name: str) -> None:
    """Log asset names to a text file for pattern analysis"""
    asset_logs_dir = Path.cwd() / "asset logs"
    asset_logs_dir.mkdir(exist_ok=True)

    asset_log_file = asset_logs_dir / "scanned_assets.txt"

    # Append to the file as CSV
    with open(asset_log_file, 'a', encoding='utf-8') as f:
        f.write(f"{entity_name},{asset_name},{zone_name}\n")


async def _setup_katsuba_search(client: Client, entity_names: list[str]) -> dict[str, dict]:
    """
    Sets up katsuba search and finds file paths for all given entity names.
    Returns a dictionary mapping entity_name -> {"file_path": str, "data": dict}
    """
    logger.info("Setting up katsuba search")

    revision, zone_name = await get_revision_and_zone(client)
    logger.info(f"Katsuba search for {zone_name} zone... searching for {len(entity_names)} entities")

    # Extract root zone from zone_name for WorldData.wad lookup
    root_zone = zone_name.split('/')[0]
    world_data_path = fr"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData\{root_zone}-WorldData.wad"
    logger.info(f"Root zone extracted: {root_zone}")
    logger.info(f"Looking for WorldData file at: {world_data_path}")

    type_list = TypeList.open(Path.cwd() / "types" / f"{revision}.json")
    opts = SerializerOptions()
    opts.flags |= STATEFUL_FLAGS
    opts.shallow = False
    opts.skip_unknown_types = True
    ser = Serializer(opts, type_list)
    logger.info(f"Katsuba SerializerOptions configured -> Flags: {opts.flags} -> Shallow: {opts.shallow}")
    logger.warning("Archive (Root.wad) path is hard coded, remember to change in production code for people with steam")
    archive = Archive.mmap(r"C:\ProgramData\KingsIsle Entertainment\Wizard101\Data\GameData\Root.wad")

    # Create a set for faster lookups
    entity_names_set = set(f"{name}.xml" for name in entity_names)
    entity_data_map = {}

    # Single pass through ObjectData files
    for file_path in archive.iter_glob("ObjectData/**/*.xml"):
        filename = file_path.split("/")[-1]  # Get just the filename
        if filename in entity_names_set:
            entity_name = filename[:-4]  # Remove .xml extension
            logger.info(f"Found {entity_name}: {file_path}")

            try:
                # Deserialize the file
                manifest = archive.deserialize(file_path, ser)
                serializable_data = _op_to_dict(type_list, manifest)

                # Store both path and data
                entity_data_map[entity_name] = {
                    "file_path": file_path,
                    "data": serializable_data
                }

                # Debug mode: write JSON files
                if DEV_MODE:
                    await _debug_write_entity_json(entity_name, serializable_data)

                # Check for StateObjects in m_assetName and log ALL assets
                behaviors = serializable_data.get("m_behaviors", [])
                for behavior in behaviors:
                    if behavior and isinstance(behavior, dict):
                        if "m_assetName" in behavior:
                            asset_name = behavior["m_assetName"]

                            # Log ALL assets to file
                            await _log_asset_to_file(entity_name, asset_name, zone_name)

                            logger.info(f"Found asset for {entity_name}: {asset_name}")

                            # Log asset discovery (NIF processing now handled in entity collision extraction)
                            if asset_name.startswith("StateObjects"):
                                logger.success(f"Found StateObjects asset for {entity_name}: {asset_name}")
                            elif asset_name.endswith(".nif"):
                                logger.debug(f"Found NIF asset for {entity_name}: {asset_name}")

            except Exception as e:
                logger.error(f"Failed to deserialize {entity_name}: {e}")

    # Log any entities that weren't found
    found_entities = set(entity_data_map.keys())
    missing_entities = set(entity_names) - found_entities
    if missing_entities:
        logger.warning(f"Could not find files for entities: {missing_entities}")

    logger.info(f"Found {len(entity_data_map)} out of {len(entity_names)} entities")
    return entity_data_map


async def _get_entity_collision_shapes(client: Client, static_body_radius: float, player_height: float) -> list[Polygon]:
    """
    Gets entities and creates accurate collision shapes using NIF data with player height awareness.
    Uses height-aware NIF extraction for complex shapes, bounding boxes for fallbacks.
    
    Args:
        client: Game client for accessing entity data
        static_body_radius: Default radius for non-character entities
        player_height: Player height for height-aware collision sampling
    """
    logger.info("Getting dynamic entity collision shapes...")
    entity_shapes = []
    try:
        entity_list = await client.get_base_entity_list()

        # Collect all entity names first
        entity_names = []
        for entity in entity_list:
            entity_name = await entity.object_name()
            entity_names.append(entity_name)

        # Single katsuba search for all entities
        entity_data_map = await _setup_katsuba_search(client, entity_names)

        # Now process each entity with its found data
        for entity in entity_list:
            entity_name = await entity.object_name()
            entity_info = entity_data_map.get(entity_name)

            if entity_name == "Player Object":
                continue

            # Skip collision detection for trigger entities - we need to walk through them
            if ("trigger" in entity_name.lower() or 
                "door" in entity_name.lower() or 
                entity_name.startswith("DynaTrigger_")):
                logger.debug(f"Skipping collision for trigger entity: {entity_name}")
                continue

            entity_loc = await entity.location()
            collision_shape = None

            # Try to get NIF-based collision shape if we have asset data
            nif_found = False
            if entity_info:
                file_path = entity_info["file_path"]
                data = entity_info["data"]
                logger.debug(f"Processing {entity_name} from {file_path}")
                
                # Look for asset paths in the entity data
                try:
                    serializable_data = data
                    behaviors = serializable_data.get("m_behaviors", [])
                    for behavior in behaviors:
                        if behavior and isinstance(behavior, dict):
                            if "m_assetName" in behavior:
                                asset_name = behavior["m_assetName"]
                                if asset_name.endswith(".nif"):
                                    nif_found = True
                                    logger.debug(f"Attempting NIF collision extraction for {entity_name}: {asset_name}")
                                    try:
                                        collision_shape = await get_entity_collision_shape(client, entity_name, asset_name, player_height)
                                        break  # Use first NIF found
                                    except Exception as e:
                                        logger.warning(f"Failed to get NIF collision for {entity_name}: {e}")
                except Exception as e:
                    logger.debug(f"Error processing entity data for {entity_name}: {e}")

            # If no NIF found, skip this entity (assume no collision)
            if not nif_found:
                logger.debug(f"No NIF found for {entity_name}, skipping collision (assumed no collision)")
                continue

            # Handle different collision shape types from NIF processing
            if isinstance(collision_shape, Polygon):
                # Single polygon - translate to entity location
                from shapely.affinity import translate
                translated_shape = translate(collision_shape, xoff=entity_loc.x, yoff=entity_loc.y)
                entity_shapes.append(translated_shape)
                logger.debug(f"Used single NIF collision polygon for {entity_name}")
            elif isinstance(collision_shape, list):
                # Multiple polygons (e.g., chair legs) - translate each one
                from shapely.affinity import translate
                for i, poly in enumerate(collision_shape):
                    if isinstance(poly, Polygon):
                        translated_poly = translate(poly, xoff=entity_loc.x, yoff=entity_loc.y)
                        entity_shapes.append(translated_poly)
                logger.success(f"Used {len(collision_shape)} NIF collision polygons for {entity_name}")
            elif isinstance(collision_shape, (int, float)) and collision_shape > 0:
                # Radius fallback from NIF processing - use bounding box approximation for better accuracy
                entity_radius = collision_shape
                logger.debug(f"Using NIF-derived radius for {entity_name}: {entity_radius:.2f}")
                # Create a square bounding box instead of a circle for better collision approximation
                from shapely.geometry import box
                bbox = box(entity_loc.x - entity_radius, entity_loc.y - entity_radius,
                          entity_loc.x + entity_radius, entity_loc.y + entity_radius)
                entity_shapes.append(bbox)
                logger.debug(f"Created bounding box collision for {entity_name} (more accurate than circle)")
            else:
                # NIF processing failed, but we know there should be a NIF - use CharacterBody fallback only
                actor_body = await entity.actor_body()
                if actor_body and await actor_body.read_type_name() == "CharacterBody":
                    entity_height = await actor_body.height()
                    entity_scale = await actor_body.scale()
                    entity_radius = entity_height * entity_scale * 0.5
                    logger.debug(f"NIF failed, using CharacterBody bounding box for '{entity_name}': {entity_radius:.2f}")
                    if entity_radius > 0:
                        # Use bounding box instead of circle for CharacterBody entities too
                        from shapely.geometry import box
                        bbox = box(entity_loc.x - entity_radius, entity_loc.y - entity_radius,
                                  entity_loc.x + entity_radius, entity_loc.y + entity_radius)
                        entity_shapes.append(bbox)
                        logger.debug(f"Created CharacterBody bounding box collision for {entity_name}")
                else:
                    logger.debug(f"NIF failed and no CharacterBody for {entity_name}, skipping collision")

    except Exception as e:
        logger.error(f"An error occurred while getting entity collision shapes: {e}", exc_info=True)

    # Enhanced collision summary logging
    if entity_shapes:
        polygon_count = sum(1 for shape in entity_shapes if hasattr(shape, 'geom_type') and shape.geom_type == 'Polygon')
        bbox_count = len(entity_shapes) - polygon_count
        logger.success(f"Generated {len(entity_shapes)} collision shapes from dynamic entities:")
        logger.info(f"  - {polygon_count} NIF-based polygon shapes (accurate geometry)")
        logger.info(f"  - {bbox_count} bounding box approximations (improved from circles)")
    else:
        logger.info("No entity collision shapes generated.")
    
    return entity_shapes



def _export_collision_polygons(file_path: Path, shapes: List[Polygon]):
    """Saves the calculated collision polygons to a file."""
    try:
        with open(file_path, "w") as f:
            for poly in shapes:
                if isinstance(poly, Polygon):
                    f.write(poly.wkt + "\n")
        logger.success(f"Successfully exported collision polygons to {file_path}")
    except Exception as e:
        logger.error(f"Failed to export collision polygons: {e}")


def _plot_collision_map(
        sane_zone_name: str,
        file_suffix: str,
        player_pos: XYZ,
        target_pos: XYZ,
        quest_id: int,
        mesh_shapes: List[Polygon],
        coll_shapes: List[Polygon],
        safe_point: XYZ = None,
        nearby_entities: List[tuple[DynamicClientObject, XYZ, str]] = None
):
    """Generates and saves a plot of the collision map."""
    image_dir = Path("images")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plot_path = image_dir / f"{sane_zone_name}_Q{quest_id}_{timestamp}_{file_suffix}.png"

    fig, ax = plt.subplots(figsize=(10, 10))

    if mesh_shapes:
        for m in mesh_shapes:
            # Validate geometry type before accessing .exterior
            if hasattr(m, 'geom_type') and m.geom_type == 'Polygon' and hasattr(m, 'exterior'):
                ax.add_patch(
                    MplPoly(list(m.exterior.coords), closed=True, fill=True, alpha=0.2, edgecolor='green', linewidth=1))

    if coll_shapes:
        for c in coll_shapes:
            # Validate geometry type before accessing .exterior
            if hasattr(c, 'geom_type') and c.geom_type == 'Polygon' and hasattr(c, 'exterior'):
                ax.add_patch(
                    MplPoly(list(c.exterior.coords), closed=True, fill=True, alpha=0.3, edgecolor='red', linewidth=1))

    ax.plot(player_pos.x, player_pos.y, 'bo', markersize=8, label='Player Start')
    ax.plot(target_pos.x, target_pos.y, 'rx', markersize=12, mew=2, label='Quest Target')
    if safe_point:
        ax.plot(safe_point.x, safe_point.y, '*', color='cyan', markersize=15, label='Teleport Point')

    if nearby_entities:
        entity_x = [e[1].x for e in nearby_entities]
        entity_y = [e[1].y for e in nearby_entities]
        ax.plot(entity_x, entity_y, 'v', color='orange', markersize=8, label='Nearby Entities (Post-TP)')
        for entity, loc, name in nearby_entities:
            ax.text(loc.x, loc.y, f"  {name}", fontsize=8, color='darkorange')

    ax.set_aspect('equal', 'box')
    ax.legend()
    ax.set_title(f"{sane_zone_name} - {file_suffix}\nQuest ID: {quest_id}")
    ax.grid(True, linestyle='--', alpha=0.6)

    plt.savefig(plot_path)
    plt.close(fig)
    print(f"Saved collision map to {plot_path}")


async def _check_for_nearby_entities(client: Client, teleport_pos: XYZ, player_radius: float) -> List[
    tuple[DynamicClientObject, XYZ, str]]:
    """
    Checks for non-player entities that are colliding with the player's radius post-teleport.
    Returns a list of tuples containing the entity object, its location, and its name.
    """
    logger.info(f"Checking for entity collisions with player radius {player_radius:.2f} at {teleport_pos}...")
    colliding_entities = []
    try:
        entity_list = await client.get_base_entity_list()
        for entity in entity_list:
            entity_name = await entity.object_name()
            if entity_name == "Player Object":
                continue

            actor_body = await entity.actor_body()
            if not actor_body:
                continue

            entity_loc = await actor_body.position()
            entity_height = await actor_body.height()
            entity_scale = await actor_body.scale()

            entity_radius = entity_height * entity_scale * 0.5
            distance = math.dist((teleport_pos.x, teleport_pos.y), (entity_loc.x, entity_loc.y))

            if distance < (player_radius + entity_radius):
                logger.warning(
                    f"Collision detected with entity: '{entity_name}' at {entity_loc}. "
                    f"Distance: {distance:.2f}, "
                    f"Combined Radii: {(player_radius + entity_radius):.2f}"
                )
                colliding_entities.append((entity, entity_loc, entity_name))

    except Exception as e:
        logger.error(f"An error occurred while checking for nearby entities: {e}", exc_info=True)

    if not colliding_entities:
        logger.success("No entity collisions detected post-teleport.")

    return colliding_entities


async def _perform_single_teleport_attempt(
        client: Client,
        free_area: Union[Polygon, MultiPolygon],
        target: XYZ,
        bounds: tuple,
        base_player_radius: float,
        player_radius_offset: float,
        quest_id: int,
        sane_zone_name: str,
        mesh_shapes: List[Polygon],
        all_coll_shapes: List[Polygon],
        player_pos: XYZ
) -> bool:
    """Performs a single, non-looping teleport attempt and verifies the result."""
    epsilon = base_player_radius * 0.1
    player_radius = base_player_radius * player_radius_offset
    minx, miny, maxx, maxy = bounds

    logger.info(
        f"Performing single teleport attempt with offset={player_radius_offset:.2f}, radius={player_radius:.2f}")

    if not free_area or free_area.is_empty:
        logger.error("Free area is empty, cannot calculate a safe region.")
        return False

    safe_region = free_area.buffer(-player_radius)
    if not safe_region or safe_region.is_empty:
        logger.error("Safe region is empty after buffering. Cannot find a teleport point.")
        return False

    # Use radius offset to progressively search further from target
    # Higher offset = search further away from problematic target area
    search_distance = (player_radius_offset - 1.0) * 300  # 0, 60, 120, 180, 240 units away
    target_point = Point(target.x, target.y)
    
    if search_distance <= 0:
        # First attempt: try nearest point to exact target
        _, candidate_pt = nearest_points(target_point, safe_region)
        safe_pt = XYZ(candidate_pt.x, candidate_pt.y, target.z)
        logger.info(f"Calculated nearest safe_pt to target: {safe_pt}")
    else:
        # Later attempts: look for safe areas further from the problematic target location
        target_area = target_point.buffer(search_distance)
        intersection = target_area.intersection(safe_region)
        
        if intersection and not intersection.is_empty:
            # Find a point in the safe area that's roughly the search distance away
            if hasattr(intersection, 'centroid'):
                candidate_pt = intersection.centroid
            else:
                # Fallback to boundary if no centroid
                candidate_pt = intersection.boundary.centroid if hasattr(intersection, 'boundary') else target_point
            
            safe_pt = XYZ(candidate_pt.x, candidate_pt.y, target.z)
            logger.info(f"Calculated alternative safe_pt at ~{search_distance:.0f} units from target: {safe_pt}")
        else:
            # Fallback to nearest point if no intersection found
            _, candidate_pt = nearest_points(target_point, safe_region)
            safe_pt = XYZ(candidate_pt.x, candidate_pt.y, target.z)
            logger.info(f"Fallback to nearest safe_pt (no intersection at distance {search_distance:.0f}): {safe_pt}")

    cx = min(max(safe_pt.x, minx), maxx)
    cy = min(max(safe_pt.y, miny), maxy)
    safe_pt = XYZ(cx, cy, safe_pt.z)
    logger.info(f"Clamped safe_pt to instance bounds: {safe_pt}")

    # Store starting zone name before teleport
    start_zone_name = await client.zone_name()

    await client.teleport(safe_pt)

    # Give client time to process teleport and potentially load a new zone
    logger.info("Waiting for server to confirm position or zone change...")
    await asyncio.sleep(3.5)

    # --- NEW VERIFICATION LOGIC ---
    new_pos = await client.body.position()
    end_zone_name = await client.zone_name()
    is_loading = await client.is_loading()

    logger.info(f"Position after TP and sleep: {new_pos}")
    logger.info(f"Zone after TP: '{end_zone_name}', Loading: {is_loading}")

    # Check for success via zone change first
    if is_loading or start_zone_name != end_zone_name:
        logger.success("Teleport successful: Zone change detected.")
        return True

    # If still in the same zone, check for position error
    error = math.dist((new_pos.x, new_pos.y), (safe_pt.x, safe_pt.y))
    logger.info(f"Post-teleport 2D error={error:.2f}, Epsilon Threshold={epsilon:.2f}")

    colliding_entities = await _check_for_nearby_entities(client, new_pos, player_radius)
    _plot_collision_map(
        sane_zone_name, "teleport_attempt", player_pos, target, quest_id,
        mesh_shapes, all_coll_shapes, safe_point=safe_pt, nearby_entities=colliding_entities
    )

    if error < epsilon:
        logger.success("Teleport to safe point appears successful based on position error.")
        pre_goto_pos = await client.body.position()
        await client.goto(target.x, target.y)
        await asyncio.sleep(1.5)
        post_goto_pos = await client.body.position()
        distance_moved = math.dist((pre_goto_pos.x, pre_goto_pos.y), (post_goto_pos.x, post_goto_pos.y))

        if distance_moved > 10.0:
            logger.success(f"Movement verification PASSED. Moved {distance_moved:.2f} units after goto.")
            return True
        else:
            logger.error(f"Movement verification FAILED. Only moved {distance_moved:.2f} units. Player may be stuck.")
            logger.info(f"Movement verification might not have failed. We should try pressing x and see what happens. "
                        f"\nLikely can be fixed/patched outside of CollisionTP")
            return False
    else:
        logger.error("Teleport to safe point FAILED. Player was likely rubber-banded.")
        
        # Add the failed teleport location as a dynamic collision zone
        zone_name = await client.zone_name()
        await _add_or_expand_dynamic_collision_zone(safe_pt, zone_name, player_radius, client)
        
        return False


# </editor-fold>

async def WorldsCollideTP(
        client: Client,
        player_radius_offset: float = 1,
        static_body_radius: float = 75.0,
        plots: bool = True,
        debug: bool = True
):
    """
    Handles teleportation to a quest target by calculating a safe path around ALL collision geometry,
    including dynamic entities.
    """
    output_file_path, sane_zone_name = await _setup_export_paths(client)
    player_pos = await client.body.position()
    target = await client.quest_position.position()
    client_character_registry = await client.character_registry()
    quest_id = await client_character_registry.active_quest_id()
    logger.info(f"Player position: {player_pos}")
    logger.info(f"Quest target: {target}")
    logger.info(f"Quest ID: {quest_id}")

    world, static_coll_shapes, mesh_shapes = await _load_and_build_collision_geometry(client, target.z, debug)
    
    # Get player height early for height-aware collision detection
    player_height = await client.body.height()
    player_scale = await client.body.scale()
    logger.debug(f"Player height: {player_height:.1f}, scale: {player_scale:.2f}")
    
    entity_coll_shapes = await _get_entity_collision_shapes(client, static_body_radius, player_height)

    # Filter out any invalid geometries to prevent LineString crashes
    static_coll_shapes = filter_valid_polygons(static_coll_shapes)
    entity_coll_shapes = filter_valid_polygons(entity_coll_shapes)
    mesh_shapes = filter_valid_polygons(mesh_shapes)

    # Add dynamic collision zones discovered from previous rubber-band failures
    zone_name = await client.zone_name()
    
    # Load any previously saved dynamic collision zones for this zone
    await _load_dynamic_collision_zones(client, zone_name)
    
    dynamic_coll_shapes = _get_dynamic_collision_polygons(zone_name)
    dynamic_coll_shapes = filter_valid_polygons(dynamic_coll_shapes)

    all_coll_shapes = static_coll_shapes + entity_coll_shapes + dynamic_coll_shapes
    logger.info(f"Total collision objects (static + dynamic + learned): {len(static_coll_shapes)} + {len(entity_coll_shapes)} + {len(dynamic_coll_shapes)} = {len(all_coll_shapes)}")

    _export_collision_polygons(output_file_path, all_coll_shapes + mesh_shapes)

    union_all_coll = unary_union(all_coll_shapes) if all_coll_shapes else Polygon()
    union_mesh = unary_union(mesh_shapes) if mesh_shapes else Polygon()

    free_area = union_mesh.difference(union_all_coll)

    bounds_geom = union_mesh if not union_mesh.is_empty else union_all_coll
    if bounds_geom.is_empty:
        logger.error("No geometry (mesh or collision) found to define zone boundaries. Aborting.")
        return
    bounds = bounds_geom.bounds
    logger.info(f"Instance bounds: X[{bounds[0]:.1f},{bounds[2]:.1f}]  Y[{bounds[1]:.1f},{bounds[3]:.1f}]")

    if plots:
        # Generate enhanced collision plots
        zone_name = await client.zone_name()
        generate_collision_plots(static_coll_shapes, entity_coll_shapes, player_pos, target, target, zone_name, debug=True)
        
        # Also generate the original combined plot for backward compatibility
        _plot_collision_map(sane_zone_name, "initial_map_with_entities", player_pos, target, quest_id, mesh_shapes,
                            all_coll_shapes)

    base_player_radius = player_height * player_scale * 0.5
    player_radius = base_player_radius * player_radius_offset
    logger.info(f"Estimated player radius (offset applied): {player_radius:.2f}")

    player_at_target = Point(target.x, target.y).buffer(player_radius)

    if not union_all_coll.intersects(player_at_target):
        logger.info(
            "Quest target is clear of all known collision objects. Attempting direct teleport...")
        start_zone_name = await client.zone_name()
        start_position = await client.body.position()
        
        await client.teleport(target)
        await asyncio.sleep(3)
        
        # Validate teleport success by checking position and zone changes
        end_position = await client.body.position()
        end_zone_name = await client.zone_name()
        
        # Calculate distance moved
        distance_moved = ((end_position.x - start_position.x) ** 2 + 
                         (end_position.y - start_position.y) ** 2) ** 0.5
        
        if await client.is_loading() or start_zone_name != end_zone_name:
            logger.success("Direct teleport resulted in a zone change.")
            return
        elif distance_moved > 100:  # Minimum significant movement threshold
            logger.success(f"Direct teleport successful - moved {distance_moved:.1f} units.")
            return
        else:
            logger.warning(f"Direct teleport failed - only moved {distance_moved:.1f} units. Falling back to collision pathfinding.")
            # Continue to collision-based pathfinding below

    logger.warning("Quest target is inside a combined collision object. Calculating safe teleport point.")

    success = await _perform_single_teleport_attempt(
        client, free_area, target, bounds, base_player_radius, player_radius_offset,
        quest_id, sane_zone_name, mesh_shapes, all_coll_shapes, player_pos
    )

    if success:
        logger.success("Collision-based teleportation was successful.")
    else:
        logger.error("Collision-based teleportation failed.")

def build_collision_shapes(world: CollisionWorld, z_slice: float, debug: bool = False) -> List[Polygon]:
    shapes = []
    if debug:
        print("--- Starting to build collision shapes ---")

    for i, obj in enumerate(world.objects):
        try:
            if obj.proxy == ProxyType.BOX:
                l, w, h = obj.params.length, obj.params.width, obj.params.depth
                if obj.location[2] - h / 2 <= z_slice <= obj.location[2] + h / 2:
                    verts = toCubeVertices((l, w, h))
                    world_pts = transformCube(verts, obj.location, obj.rotation)
                    pts2d = [(p[0], p[1]) for p in world_pts]
                    if len(pts2d) >= 3:
                        shapes.append(Polygon(pts2d).convex_hull)

            elif obj.proxy == ProxyType.SPHERE:
                scale_val = obj.scale if isinstance(obj.scale, (float, int)) else obj.scale[0]
                r = obj.params.radius * scale_val
                if r > 0 and abs(z_slice - obj.location[2]) <= r:
                    shapes.append(Point(obj.location[0], obj.location[1]).buffer(r))

            elif obj.proxy == ProxyType.CYLINDER:
                if isinstance(obj.scale, (float, int)):
                    scale_xy, scale_z = obj.scale, obj.scale
                else:
                    scale_xy, scale_z = obj.scale[0], obj.scale[2]

                scaled_half_length = (obj.params.length / 2) * scale_z
                scaled_radius = obj.params.radius * scale_xy * 0.125
                if scaled_radius > 0 and obj.location[2] - scaled_half_length <= z_slice <= obj.location[
                    2] + scaled_half_length:
                    shapes.append(Point(obj.location[0], obj.location[1]).buffer(scaled_radius))

        except Exception as e:
            print(f"  - ERROR processing object {i} ('{obj.name}'): {e}")
            continue

    if debug:
        print("\n--- Finished building collision shapes ---")
    return shapes


def build_mesh_shapes(world: CollisionWorld, z_slice: float) -> List[Polygon]:
    shapes = []
    for obj in world.objects:
        if obj.proxy == ProxyType.MESH:
            pts3d = transformCube(obj.vertices, obj.location, obj.rotation)
            pts2d = [(x, y) for x, y, z in pts3d]
            if len(pts2d) >= 3:
                shapes.append(Polygon(pts2d).convex_hull)
    return shapes


async def get_revision_and_zone(client: Client) -> tuple[str, str]:
    try:
        process = WindowsProcess.from_name("WizardGraphicalClient.exe")
        wiz_bin = Path(process.executable_path).parent
        revision_file = wiz_bin / "revision.dat"

        if not revision_file.exists():
            raise FileNotFoundError(f"revision.dat not found in {wiz_bin}")

        revision = revision_file.read_text().strip()
        zone_name = await client.zone_name()
        return revision, zone_name
    except Exception as e:
        logger.error(f"Could not get revision and zone: {e}")
        return "unknown_revision", "unknown_zone"


async def main():
    """Main function to run the teleport script in a loop, triggered by spacebar."""
    print("Script started. Press SPACE to teleport. Press ESC to exit.")
    handler = ClientHandler()
    try:
        # Get the client once at the start
        client = handler.get_new_clients()[0]
        print("Client found. Ready.")
        await client.activate_hooks()

        while True:
            # Check for exit condition
            if keyboard.is_pressed('1'):
                print("Escape key pressed. Exiting...")
                break

            # Check for trigger condition
            if keyboard.is_pressed('space'):
                print("\nSpacebar pressed. Running WorldsCollideTP...")
                try:
                    await WorldsCollideTP(
                        client,
                        player_radius_offset=0.5,
                        static_body_radius=75.0,  # Tune this value for non-character objects
                        plots=True,
                        debug=False
                    )
                    print("\nWorldsCollideTP finished. Waiting for next spacebar press...")
                    # Wait for space to be released to avoid multiple triggers
                    while keyboard.is_pressed('space'):
                        await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"An error occurred during WorldsCollideTP execution: {e}", exc_info=True)

            # Prevent the loop from running too fast
            await asyncio.sleep(0.1)

    except IndexError:
        logger.error("No Wizard101 client found.")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the main loop: {e}", exc_info=True)
    finally:
        print("Closing client handler.")
        await handler.close()


if __name__ == "__main__":
    logger.add("worlds_collide.log", rotation="5 MB", level="DEBUG")
    asyncio.run(main())