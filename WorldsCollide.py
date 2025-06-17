import asyncio
import inspect
import math
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Coroutine, Sequence, Union, List

# Added import for keyboard listening
import keyboard
from loguru import logger
import numpy as np
import matplotlib
from memobj import WindowsProcess
from wizwalker.memory import DynamicClientObject, ActorBody
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union, nearest_points

from src.utils import is_free

# DEV flag to control destructive actions like deleting directories
DEV_MODE = True

# Use 'Agg' backend for saving plots to file without GUI issues
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPoly

from wizwalker import Client, ClientHandler, XYZ
from src.collision import get_collision_data, CollisionWorld, ProxyType
from src.collision_math import toCubeVertices, transformCube


# <editor-fold desc="Refactored Helper Functions">

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
    return world, coll_shapes, mesh_shapes


async def _get_entity_collision_shapes(client: Client, static_body_radius: float) -> List[Polygon]:
    """
    Gets entities and approximates their collision shapes as circles.
    Uses a dynamic radius for 'CharacterBody' and a static default radius for ALL other types.
    """
    logger.info("Getting dynamic entity collision shapes...")
    entity_shapes = []
    try:
        entity_list = await client.get_base_entity_list()
        for entity in entity_list:
            entity_name = await entity.object_name()
            if entity_name == "Player Object":
                continue

            entity_loc = await entity.location()
            entity_radius = 0.0

            # NEW LOGIC: Default to static radius unless it's a character.
            actor_body = await entity.actor_body()

            # Check for actor_body and if its type is CharacterBody
            if actor_body and await actor_body.read_type_name() == "CharacterBody":
                entity_height = await actor_body.height()
                entity_scale = await actor_body.scale()
                entity_radius = entity_height * entity_scale * 0.5
                logger.debug(f"Calculating dynamic radius for '{entity_name}' (CharacterBody): {entity_radius:.2f}")
            else:
                # Apply static radius to ALL other cases (StaticBody, bodiless ClientObjects, etc.)
                entity_radius = static_body_radius
                actor_type_str = await actor_body.read_type_name() if actor_body else "None"
                logger.debug(
                    f"Applying static radius for '{entity_name}' (Type: {actor_type_str}): {entity_radius:.2f}")

            if entity_radius > 0:
                entity_shapes.append(Point(entity_loc.x, entity_loc.y).buffer(entity_radius))

    except Exception as e:
        logger.error(f"An error occurred while getting entity collision shapes: {e}", exc_info=True)

    logger.success(f"Generated {len(entity_shapes)} collision shapes from dynamic entities.")
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
            ax.add_patch(
                MplPoly(list(m.exterior.coords), closed=True, fill=True, alpha=0.2, edgecolor='green', linewidth=1))

    if coll_shapes:
        for c in coll_shapes:
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

    _, pt2 = nearest_points(Point(target.x, target.y), safe_region)
    safe_pt = XYZ(pt2.x, pt2.y, target.z)
    logger.info(f"Calculated candidate safe_pt: {safe_pt}")

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
        return False


# </editor-fold>

async def WorldsCollideTP(
        client: Client,
        player_radius_offset: float = 0.5,
        static_body_radius: float = 75.0,
        plots: bool = True,
        debug: bool = False
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
    entity_coll_shapes = await _get_entity_collision_shapes(client, static_body_radius)

    all_coll_shapes = static_coll_shapes + entity_coll_shapes
    logger.info(f"Total collision objects (static + dynamic): {len(all_coll_shapes)}")

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
        _plot_collision_map(sane_zone_name, "initial_map_with_entities", player_pos, target, quest_id, mesh_shapes,
                            all_coll_shapes)

    player_height = await client.body.height()
    player_scale = await client.body.scale()
    base_player_radius = player_height * player_scale * 0.5
    player_radius = base_player_radius * player_radius_offset
    logger.info(f"Estimated player radius (offset applied): {player_radius:.2f}")

    player_at_target = Point(target.x, target.y).buffer(player_radius)

    if not union_all_coll.intersects(player_at_target):
        logger.info(
            "Quest target is clear of all known collision objects. Attempting direct teleport...")
        start_zone_name = await client.zone_name()
        await client.teleport(target)
        await asyncio.sleep(3)
        if await client.is_loading() or start_zone_name != await client.zone_name():
            logger.success("Direct teleport resulted in a zone change.")
        return

    logger.warning("Quest target is inside a combined collision object. Calculating safe teleport point.")

    success = await _perform_single_teleport_attempt(
        client, free_area, target, bounds, base_player_radius, player_radius_offset,
        quest_id, sane_zone_name, mesh_shapes, all_coll_shapes, player_pos
    )

    if success:
        logger.success("Collision-based teleportation was successful.")
    else:
        logger.error("Collision-based teleportation failed. Falling back to navmap.")
        if await try_navmap_then(client, target):
            logger.success("Navmap fallback was successful.")
        else:
            logger.critical("FATAL: Both collision-TP and navmap-TP have failed.")


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


async def try_navmap_then(client: Client, xyz: XYZ, sigma: float = 5.0) -> bool:
    from src.teleport_math import calc_Distance, navmap_tp
    start_zone = await client.zone_name()
    start_pos = await client.body.position()

    logger.info(f"Calling navmap_tp to {xyz}")
    await navmap_tp(client, xyz)
    await asyncio.sleep(1)

    curr_pos = await client.body.position()
    curr_zone = await client.zone_name()
    moved = calc_Distance(start_pos, curr_pos) > sigma
    zone_changed = (curr_zone != start_zone)
    still_free = await is_free(client)

    logger.info(f"Navmap result: moved={moved}, zone_changed={zone_changed}, still_free={still_free}")
    return (moved or zone_changed or not still_free)


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