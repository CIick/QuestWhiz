# Copyright 2022 PeechezNCreem
#
# Licensed under the ISC license:
#
# Permission to use, copy, modify, and/or distribute this software for any purpose with
# or without fee is hereby granted, provided that the above copyright notice and this
# permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD
# TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN
# NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR
# CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR
# PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
# ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

from __future__ import annotations

import struct
import json
import time
from dataclasses import dataclass, field
from enum import Enum, Flag # We import Flag specifically for our CollisionFlag enum
from io import BytesIO
from pathlib import Path
from typing import TypeAlias, List, Optional, Tuple, Union
from xml.etree import ElementTree as etree
from wizwalker import Wad, Client, XYZ
import numpy as np
from loguru import logger
from shapely.geometry import Polygon, Point, MultiPolygon

# Monkey-patch time.clock for pyffi compatibility
if not hasattr(time, "clock"):
    time.clock = time.perf_counter

Matrix3x3: TypeAlias = tuple[
    float, float, float,
    float, float, float,
    float, float, float,
]
SimpleFace: TypeAlias = tuple[int, int, int]
SimpleVert: TypeAlias = tuple[float, float, float]
Vector3D: TypeAlias = tuple[float, float, float]


class StructIO(BytesIO):
    def read_string(self) -> str:
        length, = self.unpack("<i")
        return self.read(length).decode()

    def unpack(self, fmt: str) -> tuple:
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))


def flt(x: str) -> str:
    x, y = str(round(x, 4)).split(".")

    y = y.ljust(4, "0")

    return f"{x}.{y}"


class ProxyType(Enum):
    BOX = 0
    RAY = 1
    SPHERE = 2
    CYLINDER = 3
    TUBE = 4
    PLANE = 5
    MESH = 6
    INVALID = 7

    @property
    def xml_value(self) -> str:
        return str(self).split(".")[1].lower()

# By inheriting from 'Flag', we create an enum where members can be combined using
# bitwise operators (like OR, AND). This is perfect for representing things
# like collision layers, where an object can be in multiple categories at once.
class CollisionFlag(Flag):
    # Bitwiz/Bitshift
    OBJECT = 1 << 0        # Value is 1
    WALKABLE = 1 << 1      # Value is 2
                           # Skip 4? Or am I wrong
    HITSCAN = 1 << 3       # Value is 8
    LOCAL_PLAYER = 1 << 4  # Value is 16
    WATER = 1 << 6         # Value is 64
    CLIENT_OBJECT = 1 << 7 # Value is 128
    TRIGGER = 1 << 8       # Value is 256
    FOG = 1 << 9           # Value is 512
    GOO = 1 << 10          # Value is 1024
    FISH = 1 << 11         # Value is 2048
    MUCK = 1 << 12         # Value is 4096
    TAR = 1 << 13   # Value is 8192

    @property
    def xml_value(self) -> str:
        # Because CollisionFlag is a Flag, we can use 'in' to check if a specific
        # flag is set within a combined value. For example, the value 13379 is a
        # combination of multiple flags. If we had a variable `my_flags = CollisionFlag(13379)`,
        # the check `CollisionFlag.WALKABLE in my_flags` would be True.
        if CollisionFlag.WALKABLE in self:
            return "CT_Walkable"
        elif CollisionFlag.WATER in self:
            return "CT_Water"
        elif CollisionFlag.TRIGGER in self:
            return "CT_Trigger"
        elif CollisionFlag.OBJECT in self:
            return "CT_Object"
        elif CollisionFlag.LOCAL_PLAYER in self:
            return "CT_LocalPlayer"
        elif CollisionFlag.HITSCAN in self:
            return "CT_Hitscan"
        elif CollisionFlag.FOG in self:
            return "CT_Fog"
        elif CollisionFlag.CLIENT_OBJECT in self:
            return "CT_ClientObject"
        elif CollisionFlag.GOO in self:
            return "CT_Goo"
        elif CollisionFlag.FISH in self:
            return "CT_Fish"
        elif CollisionFlag.MUCK in self:
            return "CT_Muck"
        elif CollisionFlag.TAR in self:
            return "CT_Tar"
        else:
            return "CT_None"


# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class GeomParams:
    proxy: ProxyType

    @classmethod
    def from_stream(cls, stream: StructIO) -> "GeomParams":
        raise NotImplementedError(f"{cls.__name__}.from_stream() not implemented")

    def save_xml(self, parent):
        # stub for XML export if you ever need it
        pass

# BOX
@dataclass
class BoxGeomParams(GeomParams):
    length: float
    width:  float
    depth:  float

    @classmethod
    def from_stream(cls, stream: StructIO) -> "BoxGeomParams":
        l, w, d = stream.unpack("<fff")
        return cls(ProxyType.BOX, l, w, d)

# RAY
@dataclass
class RayGeomParams(GeomParams):
    # depending on your engine, a ray might be (origin, direction, length)
    # here we just read three floats—adjust to your real format
    origin_offset: float
    direction_offset: float
    length: float

    @classmethod
    def from_stream(cls, stream: StructIO) -> "RayGeomParams":
        o, dir_, length = stream.unpack("<fff")
        return cls(ProxyType.RAY, o, dir_, length)

# SPHERE
@dataclass
class SphereGeomParams(GeomParams):
    radius: float

    @classmethod
    def from_stream(cls, stream: StructIO) -> "SphereGeomParams":
        (r,) = stream.unpack("<f")
        return cls(ProxyType.SPHERE, r)

# CYLINDER
@dataclass
class CylinderGeomParams(GeomParams):
    radius: float
    length: float

    @classmethod
    def from_stream(cls, stream: StructIO) -> "CylinderGeomParams":
        r, l = stream.unpack("<ff")
        return cls(ProxyType.CYLINDER, r, l)

# TUBE
@dataclass
class TubeGeomParams(GeomParams):
    radius: float
    length: float

    @classmethod
    def from_stream(cls, stream: StructIO) -> "TubeGeomParams":
        r, l = stream.unpack("<ff")
        return cls(ProxyType.TUBE, r, l)

# PLANE
@dataclass
class PlaneGeomParams(GeomParams):
    normal: tuple[float, float, float]
    distance: float

    @classmethod
    def from_stream(cls, stream: StructIO) -> "PlaneGeomParams":
        nx, ny, nz, d = stream.unpack("<ffff")
        return cls(ProxyType.PLANE, (nx, ny, nz), d)

# MESH
@dataclass
class MeshGeomParams(GeomParams):
    # Mesh parameters are handled in ProxyMesh, so this carries no extra data
    @classmethod
    def from_stream(cls, stream: StructIO) -> "MeshGeomParams":
        return cls(ProxyType.MESH)

# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProxyGeometry:
    category_flags: CollisionFlag
    collide_flag:  CollisionFlag
    name:          str          = ""
    rotation:      Matrix3x3    = (0.0,)*9
    location:      XYZ          = XYZ(0.0,0.0,0.0)
    scale:         float        = 0.0
    material:      str          = ""
    proxy:         ProxyType    = ProxyType.INVALID
    params:        GeomParams   = None

    def load(self, stream: StructIO) -> "ProxyGeometry":
        self.name     = stream.read_string()
        self.rotation = stream.unpack("<fffffffff")
        self.location = stream.unpack("<fff")
        (self.scale,) = stream.unpack("<f")
        self.material = stream.read_string()
        (ptype,)    = stream.unpack("<i")
        self.proxy   = ProxyType(ptype)

        match self.proxy:
            case ProxyType.BOX:
                self.params = BoxGeomParams.from_stream(stream)
            case ProxyType.RAY:
                self.params = RayGeomParams.from_stream(stream)
            case ProxyType.SPHERE:
                self.params = SphereGeomParams.from_stream(stream)
            case ProxyType.CYLINDER:
                self.params = CylinderGeomParams.from_stream(stream)
            case ProxyType.TUBE:
                self.params = TubeGeomParams.from_stream(stream)
            case ProxyType.PLANE:
                self.params = PlaneGeomParams.from_stream(stream)
            case ProxyType.MESH:
                self.params = MeshGeomParams.from_stream(stream)
            case _:
                raise ValueError(f"Invalid proxy type: {self.proxy}")

        return self


@dataclass
class ProxyMesh(ProxyGeometry):
    vertices: list[SimpleVert] = field(default_factory=list)
    faces: list[SimpleFace] = field(default_factory=list)
    normals: list[SimpleVert] = field(default_factory=list)

    def load(self, stream: StructIO) -> None:
        vertex_count, face_count = stream.unpack("<ii") # gives the cords of the 3d shape
        # might only need 2D not 3D for what we are doing? (NavmapTP)
        # How many points (vertices) your 3D object has.
        # How many faces (triangles, usually) your object has.
        for _ in range(vertex_count): #
            self.vertices.append(stream.unpack("<fff"))

        for _ in range(face_count):
            self.faces.append(stream.unpack("<iii"))
            self.normals.append(stream.unpack("<fff"))

        super().load(stream)

    def save_xml(self, parent: etree.Element) -> etree.Element:
        element = super().save_xml(parent)

        mesh = etree.SubElement(element, "mesh")

        vertexlist = etree.SubElement(
            mesh,
            "vertexlist",
            {"size": str(len(self.vertices))},
        )
        for x, y, z in self.vertices:
            etree.SubElement(
                vertexlist,
                "vert",
                {"x": flt(x), "y": flt(y), "z": flt(z)},
            )

        facelist = etree.SubElement(
            mesh,
            "facelist",
            {"size": str(len(self.faces))},
        )
        for a, b, c in self.faces:
            etree.SubElement(facelist, "face", {"a": str(a), "b": str(b), "c": str(c)})

        return element


@dataclass
class CollisionWorld:
    objects: list[ProxyGeometry] = field(default_factory=list)

    def load(self, raw_data: bytes) -> None:
        stream = StructIO(raw_data) # raw bytes for the whole file (mem stream)

        geometry_count, = stream.unpack("<i") # first bytes in the file is the geometry count
        for _ in range(geometry_count): # for every object in the geometry file
            # category_bits and collide_bits are for Open Dynamics Engine
            # This next line reads raw integers from the binary file. These integers
            # are the collision flags we need to interpret.
            geometry_type, category_bits, collide_bits = stream.unpack("<iII")

            # This is where the error happened. We pass an integer (like 13379) to the
            # CollisionFlag enum. The enum then checks if all the bits in that integer
            # correspond to defined flags. It failed because the bit for 8192 was set,
            # but we hadn't defined a flag for it yet.
            # Now that we have added UNKNOWN_13, this will succeed.
            #
            # For example, CollisionFlag(13379) will create a composite flag equivalent to:
            # CollisionFlag.OBJECT | WALKABLE | WATER | GOO | MUCK | UNKNOWN_13
            category = CollisionFlag(category_bits)
            collide = CollisionFlag(collide_bits)

            proxy = ProxyType(geometry_type)

            if proxy == ProxyType.MESH: # MESH is often used for floors or complex terrain
                geometry = ProxyMesh(category, collide)
            else: # Other shapes like boxes, spheres, etc.
                geometry = ProxyGeometry(category, collide)

            geometry.load(stream)
            self.objects.append(geometry)


    def save_xml(self, path: str | Path) -> etree.Element:
        world = etree.Element("world")
        for obj in self.objects:
            obj.save_xml(world)

        etree.indent(world)
        path.parent.mkdir(exist_ok=True, parents=True)
        with path.open("w") as file:
            file.write('<?xml version="1.0" encoding="utf-8" ?>\n')
            file.write(etree.tostring(world, encoding="unicode", xml_declaration=False))


# ==================== CACHE MANAGEMENT FUNCTIONS ====================

async def get_cache_directory(client: Client) -> Path:
    """Get the cache directory path based on current revision and zone."""
    # Import here to avoid circular dependency
    import sys
    sys.path.append('.')
    from WorldsCollide import get_revision_and_zone
    
    revision, zone_name = await get_revision_and_zone(client)
    
    # Split zone into world/subworld components
    zone_parts = zone_name.split('/')
    world = zone_parts[0] if len(zone_parts) > 0 else "Unknown"
    subworld = zone_parts[1] if len(zone_parts) > 1 else "Default"
    
    cache_dir = Path("calculated_collisions") / revision / world / subworld
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    return cache_dir


def load_cached_wcp_collision(cache_dir: Path, zone_name: str) -> Optional[List[Polygon]]:
    """Load cached WCP collision data if available."""
    sane_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
    wcp_file = cache_dir / f"{sane_zone_name}_collision_polygons.wcp"
    
    if not wcp_file.exists():
        logger.debug(f"No cached WCP collision data found: {wcp_file}")
        return None
    
    try:
        # Load the cached WCP file (assuming it's JSON format with polygon data)
        with open(wcp_file, 'r') as f:
            polygon_data = json.load(f)
        
        polygons = []
        for poly_coords in polygon_data:
            if len(poly_coords) >= 3:  # Need at least 3 points for a polygon
                polygons.append(Polygon(poly_coords))
        
        logger.info(f"Loaded {len(polygons)} cached collision polygons from {wcp_file}")
        return polygons
        
    except Exception as e:
        logger.warning(f"Failed to load cached WCP collision data: {e}")
        return None


def save_wcp_collision_cache(cache_dir: Path, zone_name: str, polygons: List[Polygon]) -> None:
    """Save collision polygons to WCP cache file."""
    sane_zone_name = "".join(c for c in zone_name if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
    wcp_file = cache_dir / f"{sane_zone_name}_collision_polygons.wcp"
    
    try:
        # Convert polygons to JSON-serializable format
        polygon_data = []
        for poly in polygons:
            # Validate geometry type before accessing .exterior
            if hasattr(poly, 'geom_type') and poly.geom_type == 'Polygon' and hasattr(poly, 'exterior'):
                coords = list(poly.exterior.coords)[:-1]  # Remove duplicate last point
                polygon_data.append(coords)
            elif hasattr(poly, 'geom_type'):
                logger.warning(f"Skipping non-polygon geometry in cache save: {poly.geom_type}")
            else:
                logger.warning(f"Skipping unknown geometry type in cache save: {type(poly)}")
        
        with open(wcp_file, 'w') as f:
            json.dump(polygon_data, f, indent=2)
        
        logger.info(f"Saved {len(polygons)} collision polygons to cache: {wcp_file}")
        
    except Exception as e:
        logger.error(f"Failed to save WCP collision cache: {e}")


def load_cached_nif_shapes(cache_dir: Path) -> dict:
    """Load cached NIF collision shapes."""
    nif_cache_file = cache_dir / "nif_shapes_cache.json"
    
    if not nif_cache_file.exists():
        logger.debug(f"No cached NIF shapes found: {nif_cache_file}")
        return {}
    
    try:
        with open(nif_cache_file, 'r') as f:
            cache_data = json.load(f)
        
        logger.debug(f"Loaded NIF shapes cache with {len(cache_data)} entries")
        return cache_data
        
    except Exception as e:
        logger.warning(f"Failed to load NIF shapes cache: {e}")
        return {}


def save_nif_shape_to_cache(cache_dir: Path, nif_filename: str, shape: Optional[Union[Polygon, List[Polygon]]], radius_fallback: float) -> None:
    """Save a single NIF collision shape to cache."""
    nif_cache_file = cache_dir / "nif_shapes_cache.json"
    
    # Load existing cache
    cache_data = load_cached_nif_shapes(cache_dir)
    
    # Prepare shape data
    shape_data = {
        "radius_fallback": radius_fallback,
        "generated_timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    
    # Handle different shape types
    if isinstance(shape, list):
        # Multiple polygons - store as list of coordinate arrays
        polygons_data = []
        for poly in shape:
            if poly and hasattr(poly, 'exterior'):
                coords = list(poly.exterior.coords)[:-1]  # Remove duplicate last point
                polygons_data.append(coords)
        shape_data["polygons"] = polygons_data if polygons_data else None
        shape_data["polygon"] = None  # Legacy format
    elif shape and hasattr(shape, 'exterior'):
        # Single polygon - maintain backward compatibility
        coords = list(shape.exterior.coords)[:-1]  # Remove duplicate last point
        shape_data["polygon"] = coords
        shape_data["polygons"] = None
    else:
        # No valid shape
        shape_data["polygon"] = None
        shape_data["polygons"] = None
    
    # Update cache
    cache_data[nif_filename] = shape_data
    
    try:
        with open(nif_cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        logger.debug(f"Cached NIF shape for {nif_filename}")
        
    except Exception as e:
        logger.error(f"Failed to save NIF shape cache: {e}")


def get_cached_nif_shape(cache_data: dict, nif_filename: str) -> Tuple[Optional[Union[Polygon, List[Polygon]]], Optional[float]]:
    """Get cached NIF collision shape if available."""
    if nif_filename not in cache_data:
        return None, None
    
    shape_data = cache_data[nif_filename]
    radius_fallback = shape_data.get("radius_fallback", 25.0)
    
    # Check for new multi-polygon format first
    polygons_data = shape_data.get("polygons")
    if polygons_data:
        try:
            polygons = []
            for poly_coords in polygons_data:
                if poly_coords and len(poly_coords) >= 3:
                    polygons.append(Polygon(poly_coords))
            if polygons:
                return polygons if len(polygons) > 1 else polygons[0], radius_fallback
        except Exception as e:
            logger.warning(f"Failed to reconstruct multi-polygon for {nif_filename}: {e}")
    
    # Fall back to legacy single polygon format
    polygon_coords = shape_data.get("polygon")
    if polygon_coords and len(polygon_coords) >= 3:
        try:
            polygon = Polygon(polygon_coords)
            return polygon, radius_fallback
        except Exception as e:
            logger.warning(f"Failed to reconstruct polygon for {nif_filename}: {e}")
    
    return None, radius_fallback


# ==================== NIF COLLISION EXTRACTION ====================

def extract_nif_collision_shape(nif_data: bytes, nif_filename: str, 
                               player_height: float = 200.0,
                               epsilon: float = 50.0, min_samples: int = 4, 
                               max_poly_area: float = 100000.0, 
                               slice_step: float = 5.0,
                               min_required_points: int = 10) -> Tuple[Optional[Union[Polygon, MultiPolygon, List[Polygon]]], float]:
    """
    Extract collision shapes from NIF file using player height-aware Z-scanning approach.
    Finds the base collision level, then samples the entire player height range.
    Can return single polygon, multiple polygons, or MultiPolygon for complex entities.
    
    Args:
        nif_data: Raw NIF file bytes
        nif_filename: Name of NIF file for logging
        player_height: Height of player for collision range sampling
        epsilon: DBSCAN clustering distance parameter
        min_samples: Minimum points required for DBSCAN cluster
        max_poly_area: Maximum allowed polygon area
        slice_step: Z-axis step size for scanning
        min_required_points: Minimum points required in base slice
    
    Returns:
        Tuple of (collision_shape, radius_fallback) where collision_shape can be:
        - Polygon: Single collision shape
        - List[Polygon]: Multiple separate collision components (e.g., chair legs)
        - MultiPolygon: Complex multi-part collision shape
        - None: No valid collision shape found
    """
    try:
        # Import pyffi here to avoid dependency issues if not available
        try:
            from pyffi.formats.nif import NifFormat
            from sklearn.cluster import DBSCAN
        except ImportError as e:
            logger.error(f"Missing dependencies for NIF processing: {e}")
            return None, 25.0
        
        # Parse NIF data
        try:
            from io import BytesIO
            nif_stream = BytesIO(nif_data)
            data = NifFormat.Data()
            data.read(nif_stream)
        except Exception as e:
            logger.error(f"Failed to parse NIF file {nif_filename}: {e}")
            return None, 25.0
        
        # Extract all vertices
        all_verts = []
        for block in data.blocks:
            if block.__class__.__name__ == "NiTriStripsData":
                all_verts.extend(block.vertices)
        
        if not all_verts:
            logger.warning(f"No vertices found in NIF {nif_filename}")
            return None, 25.0
        
        # Sort all vertices by Z to find ground level
        z_sorted = sorted(all_verts, key=lambda v: v.z)
        min_z = z_sorted[0].z
        max_z = z_sorted[-1].z
        
        # Calculate radius fallback based on model bounds
        x_coords = [v.x for v in all_verts]
        y_coords = [v.y for v in all_verts]
        x_range = max(x_coords) - min(x_coords)
        y_range = max(y_coords) - min(y_coords)
        radius_fallback = max(x_range, y_range) * 0.5
        radius_fallback = max(10.0, min(radius_fallback, 100.0))  # Clamp between 10-100
        
        # Step upward from the bottom until we find a populated Z slice (base level)
        current_z = min_z
        base_z = None
        base_points = []
        
        while current_z < max_z:
            slice_min = current_z
            slice_max = current_z + slice_step
            slice_points = [(v.x, v.y) for v in all_verts if slice_min <= v.z < slice_max]
            
            if len(slice_points) >= min_required_points:
                base_z = slice_min
                base_points = slice_points
                logger.debug(f"Found base collision level at Z={base_z:.1f} with {len(base_points)} points")
                break
            current_z += slice_step
        
        # Check if we found a valid base level
        if base_z is None or len(base_points) < 3:
            logger.warning(f"No usable base Z slice found with enough geometry in {nif_filename}")
            return None, radius_fallback
        
        # Now collect vertices from base_z to base_z + player_height for comprehensive collision
        height_range_max = base_z + player_height
        height_range_points = [(v.x, v.y) for v in all_verts if base_z <= v.z <= height_range_max]
        
        # Use height-range points if we found significantly more, otherwise stick with base
        if len(height_range_points) > len(base_points) * 1.2:  # 20% more points threshold
            collision_points = height_range_points
            additional_points = len(height_range_points) - len(base_points)
            logger.success(f"Height-aware sampling found {additional_points} additional collision points! Using {len(collision_points)} points from Z={base_z:.1f} to Z={height_range_max:.1f} (player height: {player_height:.1f})")
        else:
            collision_points = base_points
            logger.debug(f"Using base-level collision sampling: {len(collision_points)} points (height range only added {len(height_range_points) - len(base_points)} points, below threshold)")
        
        # Final validation of collision points
        if len(collision_points) < 3:
            logger.warning(f"Insufficient collision points found in {nif_filename}")
            return None, radius_fallback
        
        # Cluster and polygonize using the selected collision points
        pts = np.array(collision_points)
        
        # Auto-adjust epsilon based on point spread
        x_range = np.max(pts[:, 0]) - np.min(pts[:, 0])
        y_range = np.max(pts[:, 1]) - np.min(pts[:, 1])
        adaptive_epsilon = min(epsilon, max(x_range, y_range) * 0.1)
        
        clustering = DBSCAN(eps=adaptive_epsilon, min_samples=min_samples).fit(pts)
        labels = clustering.labels_
        unique_labels = set(labels)
        
        # Collect all valid clusters as separate polygons
        valid_polygons = []
        total_area = 0
        
        for label in unique_labels:
            if label == -1:  # Noise points
                continue
                
            cluster_points = pts[labels == label]
            if len(cluster_points) >= 3:
                try:
                    poly = Polygon(cluster_points).convex_hull
                    
                    # Check if convex_hull returned a LineString instead of Polygon
                    if hasattr(poly, 'geom_type') and poly.geom_type == 'LineString':
                        logger.debug(f"Cluster resulted in LineString, skipping cluster {label}")
                        continue
                    
                    # Accept all valid polygons within size limits
                    if poly.area <= max_poly_area and poly.area > 1.0:  # Minimum area threshold
                        valid_polygons.append(poly)
                        total_area += poly.area
                        logger.debug(f"Added cluster {label} as collision polygon (area: {poly.area:.1f})")
                except Exception as e:
                    logger.debug(f"Failed to create polygon from cluster: {e}")
                    continue
        
        # Return appropriate collision shape based on number of valid polygons
        if len(valid_polygons) == 0:
            logger.warning(f"No valid collision polygons found in {nif_filename}")
            return None, radius_fallback
        elif len(valid_polygons) == 1:
            logger.debug(f"Successfully extracted single collision polygon from {nif_filename} (area: {valid_polygons[0].area:.1f})")
            return valid_polygons[0], radius_fallback
        else:
            # Multiple polygons - return as list for now, caller can decide how to handle
            logger.success(f"Successfully extracted {len(valid_polygons)} collision polygons from {nif_filename} (total area: {total_area:.1f})")
            return valid_polygons, radius_fallback
        
    except Exception as e:
        logger.error(f"Unexpected error processing NIF {nif_filename}: {e}")
        return None, 25.0


async def get_entity_collision_shape(client: Client, entity_name: str, asset_path: str, player_height: Optional[float] = None) -> Union[Polygon, List[Polygon], float]:
    """
    Get collision shape for an entity, trying cached data first, then NIF extraction, finally radius fallback.
    Uses player height for accurate collision sampling across the entity's height range.
    
    Args:
        client: Game client for accessing player data
        entity_name: Name of the entity
        asset_path: Path to the entity's NIF asset
        player_height: Player height for collision range sampling (auto-detected if None)
    
    Returns:
        - Polygon: Single collision shape
        - List[Polygon]: Multiple collision components (e.g., chair legs)
        - float: Radius-based collision fallback
    """
    try:
        # Get player height if not provided
        if player_height is None:
            try:
                player_body = await client.body
                player_height = await player_body.height()
                player_height = player_height/2 # Testing
                logger.debug(f"Auto-detected player height: {player_height:.1f}")
            except Exception as e:
                logger.warning(f"Could not get player height for {entity_name}, using default: {e}")
                player_height = 200.0  # Default fallback height
        
        # Get cache directory and zone info
        cache_dir = await get_cache_directory(client)
        # Import here to avoid circular dependency
        import sys
        sys.path.append('.')
        from WorldsCollide import get_revision_and_zone
        revision, zone_name = await get_revision_and_zone(client)
        
        # Extract NIF filename
        nif_filename = Path(asset_path).name
        if not nif_filename.endswith('.nif'):
            logger.debug(f"Asset {asset_path} is not a NIF file, using radius fallback")
            return 25.0  # Default radius for non-NIF assets
        
        # Check NIF cache first (with player height consideration)
        nif_cache = load_cached_nif_shapes(cache_dir)
        # Create cache key that includes player height for height-aware caching
        height_key = f"{nif_filename}_h{int(player_height)}"
        cached_shape, cached_radius = get_cached_nif_shape(nif_cache, height_key)
        
        if cached_shape:
            logger.debug(f"Using cached collision shape for {entity_name} ({'multi-polygon' if isinstance(cached_shape, list) else 'single polygon'})")
            return cached_shape
        elif cached_radius:
            logger.debug(f"Using cached radius fallback for {entity_name}: {cached_radius}")
            return cached_radius
        
        # Cache miss - try to extract from NIF
        logger.info(f"Extracting collision shape from NIF for {entity_name} (first time)")
        
        try:
            # Load NIF data using pattern-based search
            nif_data = await get_nif_from_wad(asset_path, zone_name)
            
            # Extract collision shape with player height awareness
            collision_shape, radius_fallback = extract_nif_collision_shape(nif_data, nif_filename, player_height=player_height)
            
            # Cache the result with height-aware key
            save_nif_shape_to_cache(cache_dir, height_key, collision_shape, radius_fallback)
            
            if collision_shape:
                shape_type = "multi-polygon" if isinstance(collision_shape, list) else "single polygon"
                logger.success(f"Successfully extracted and cached collision shape for {entity_name} ({shape_type})")
                return collision_shape
            else:
                logger.warning(f"NIF extraction failed for {entity_name}, using radius fallback: {radius_fallback}")
                return radius_fallback
                
        except FileNotFoundError as e:
            logger.error(f"Could not find NIF file for {entity_name}: {e}")
            default_radius = 25.0
            save_nif_shape_to_cache(cache_dir, height_key, None, default_radius)
            return default_radius
        except Exception as e:
            logger.error(f"Error processing NIF for {entity_name}: {e}")
            default_radius = 25.0
            save_nif_shape_to_cache(cache_dir, height_key, None, default_radius)
            return default_radius
    
    except Exception as e:
        logger.error(f"Unexpected error in get_entity_collision_shape for {entity_name}: {e}")
        return 25.0  # Ultimate fallback


async def load_wad(path: str):
    if path is not None:
        return Wad.from_game_data(path.replace("/", "-"))


def find_nif_wad_candidates(asset_path: str, zone_name: str) -> list[str]:
    """
    Find which WAD file(s) likely contain a NIF based on its asset path.
    Based on pattern analysis from WadWatcher.py results.
    
    Returns a list of WAD candidates to try, in order of likelihood.
    """
    if asset_path.startswith('|') and '|' in asset_path[1:]:
        # Pipe-delimited format: |ArchiveName|WorldData|path → ArchiveName-WorldData.wad
        parts = asset_path.split('|')
        if len(parts) >= 2:
            archive_name = parts[1]
            return [f'{archive_name}-WorldData.wad']
    elif asset_path.startswith('StateObjects/'):
        # StateObjects: use zone-specific WorldData WAD
        root_zone = zone_name.split('/')[0]
        return [f'{root_zone}-WorldData.wad']
    else:
        # Direct path: 90% success rate in Mob-WorldData, fallback to zone and shared
        root_zone = zone_name.split('/')[0]
        return [
            'Mob-WorldData.wad',           # 90% success rate for DirectPath
            f'{root_zone}-WorldData.wad',  # Zone-specific fallback
            '_Shared-WorldData.wad'        # Shared assets fallback
        ]
    
    # Fallback for unknown patterns
    root_zone = zone_name.split('/')[0]
    return [f'{root_zone}-WorldData.wad', 'Mob-WorldData.wad', '_Shared-WorldData.wad']


async def get_nif_from_wad(asset_path: str, zone_name: str) -> bytes:
    """
    Get NIF file data from WAD using pattern-based search.
    Tries multiple WAD candidates based on asset path pattern.
    """
    # Extract just the NIF filename from the asset path
    nif_filename = Path(asset_path).name
    if not nif_filename.endswith('.nif'):
        raise ValueError(f"Asset path does not point to a NIF file: {asset_path}")
    
    # Get the actual path within the WAD (remove pipe delimiters if present)
    if asset_path.startswith('|') and asset_path.count('|') >= 2:
        # Remove pipe-delimited prefix: |Archive|WorldData|path → path
        parts = asset_path.split('|')
        if len(parts) >= 4 and parts[3]:  # Ensure we have a valid internal path
            wad_internal_path = parts[3]
            logger.debug(f"Extracted internal WAD path '{wad_internal_path}' from pipe-delimited asset: {asset_path}")
        else:
            # Malformed pipe-delimited path, extract just the filename
            wad_internal_path = nif_filename
            logger.warning(f"Malformed pipe-delimited path '{asset_path}', using filename only: {nif_filename}")
    else:
        logger.warning(f"Path is not pipe-delimited, using filename only: {nif_filename}")
        # Direct path or non-pipe-delimited
        wad_internal_path = asset_path
    
    # Get WAD candidates to try
    wad_candidates = find_nif_wad_candidates(asset_path, zone_name)
    
    # Try each WAD candidate
    failed_attempts = []
    for wad_name in wad_candidates:
        try:
            # Remove .wad extension since load_wad/Wad.from_game_data adds it automatically
            wad_name_no_ext = wad_name.replace('.wad', '') if wad_name.endswith('.wad') else wad_name
            logger.debug(f"Attempting to load WAD: {wad_name} (using name: {wad_name_no_ext})")
            
            wad = await load_wad(wad_name_no_ext)
            if wad is None:
                logger.warning(f"WAD loading returned None for: {wad_name}")
                failed_attempts.append(f"{wad_name}: WAD loading returned None")
                continue
            
            logger.success(f"Successfully loaded WAD: {wad_name}")
            logger.debug(f"Searching for NIF path '{wad_internal_path}' in {wad_name}")
                
            # Try to get the file from the WAD
            nif_data = await wad.get_file(wad_internal_path)
            if nif_data:
                # Success!
                logger.success(f"Successfully found and loaded {nif_filename} from {wad_name}")
                return nif_data
            else:
                logger.warning(f"NIF file '{wad_internal_path}' not found in {wad_name}")
                failed_attempts.append(f"{wad_name}: NIF not found in WAD")
                
        except Exception as e:
            logger.error(f"Exception while accessing {wad_name}: {e}")
            failed_attempts.append(f"{wad_name}: {str(e)}")
    
    # If we get here, all attempts failed
    error_msg = f"Failed to find {nif_filename} in any WAD.\n"
    error_msg += f"Asset path: {asset_path}\n"
    error_msg += f"Zone: {zone_name}\n"
    error_msg += f"Tried WADs: {wad_candidates}\n"
    error_msg += "Failed attempts:\n"
    for attempt in failed_attempts:
        error_msg += f"  - {attempt}\n"
    error_msg += f"→ Please search for '{nif_filename}' manually and report pattern!"
    
    raise FileNotFoundError(error_msg)


async def get_collision_data(client: Client = None, zone_name: str = None) -> bytes:
    if not zone_name and client:
        zone_name = await client.zone_name()

    elif not zone_name and not client:
        raise Exception('Client and/or zone name not provided, cannot read collision.bcd.')

    wad = await load_wad(zone_name)
    collision_data = await wad.get_file("collision.bcd")

    return collision_data