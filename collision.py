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
from dataclasses import dataclass, field
from enum import Enum, Flag # We import Flag specifically for our CollisionFlag enum
from io import BytesIO
from pathlib import Path
from typing import TypeAlias
from xml.etree import ElementTree as etree
from wizwalker import Wad, Client, XYZ

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


async def load_wad(path: str):
    if path is not None:
        return Wad.from_game_data(path.replace("/", "-"))


async def get_collision_data(client: Client = None, zone_name: str = None) -> bytes:
    if not zone_name and client:
        zone_name = await client.zone_name()

    elif not zone_name and not client:
        raise Exception('Client and/or zone name not provided, cannot read collision.bcd.')

    wad = await load_wad(zone_name)
    collision_data = await wad.get_file("collision.bcd")

    return collision_data