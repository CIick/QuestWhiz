# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Run the main quest automation bot
python BestQuest.py
# Controls: SPACE = process current quest, '1' = exit

# Run collision-aware teleportation system  
python WorldsCollide.py
# Controls: SPACE = teleport to quest location, '1' = exit

# Install dependencies
pip install -r requirements.txt
```

## Core Architecture

### Quest Processing System
**BestQuest.py** is the main automation engine that:
- Matches on-screen quest text to internal goal data using madlib text comparison
- Routes different goal types (waypoint, persona, bounty, etc.) to specialized handlers  
- Handles UI interactions: dialogue clearing, sigil entry, spiral door navigation
- Integrates with database logging and teleportation systems

### Collision-Aware Teleportation
**WorldsCollide.py** provides intelligent movement by:
- Loading binary collision data from game files (collision.bcd) 
- Converting 3D collision geometry to 2D polygons using Shapely
- Calculating safe teleport points that avoid collision with static/dynamic objects
- Generating visual collision maps and exporting data for debugging

### Collision Data Processing  
**collision.py** handles binary collision parsing:
- `CollisionWorld` loads geometry from game's collision files
- Supports BOX, SPHERE, CYLINDER, MESH, and other collision primitives
- `CollisionFlag` enum defines collision layers (WALKABLE, WATER, TRIGGER, etc.)
- Transforms world coordinates using rotation matrices

### Database Integration
**QuestDataNest.py** provides persistent quest logging:
- SQLite database stores quest metadata, goals, and madlib entries
- Translates language keys using game's internal langcode cache
- Tracks quest progression for analysis and debugging

## Key Integration Points

- BestQuest calls `WorldsCollideTP()` when standard UI navigation fails
- Quest goal matching scores text overlap between UI display and madlib data
- All systems share utilities from `utils.py` and UI paths from `paths.py`

## Important Implementation Details

- Uses WizWalker library for game memory reading and client interaction
- All client operations are async/await based
- UI interactions use path-based window finding through game's UI tree
- Zone changes detected via loading states and zone name comparison
- Player collision radius configurable via `player_radius_offset` (default 0.5)
- Database path hardcoded in QuestDataNest.py for reliability

## Dependencies

Key external libraries:
- `wizwalker` - Game memory interface (from Git repositories)
- `shapely` - 2D geometry operations  
- `matplotlib` - Collision visualization
- `numpy` - Mathematical transformations
- `keyboard` - Manual input detection