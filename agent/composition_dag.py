import math
from typing import Tuple, Any, Optional, Set
from .jev_client import JevResponse

# Canonical ViZDoom enemy actor class names (including bot players)
ENEMY_CLASSES = {
    "DoomPlayer", "Imp", "ZombieMan", "ShotgunGuy", "ChaingunGuy", "Demon", "Spectre",
    "LostSoul", "Cacodemon", "HellKnight", "BaronOfHell", "Arachnotron",
    "Mancubus", "Revenant", "Archvile", "SpiderMastermind", "CyberDemon",
    "PainElemental", "WolfensteinSS", "CommanderKeen",
}


def _get_target_bearing(target_name: str, state: Any) -> Tuple[bool, float]:
    """
    Return (found, relative_bearing_degrees) for the named target or closest visible enemy.
    β ≈ 0° = dead ahead, +90° = hard left, -90° = hard right.
    Only targets enemies in direct line-of-sight (physically rendered on screen).
    """
    if not state or not state.objects:
        return False, 0.0

    player_x     = state.game_variables[4]
    player_y     = state.game_variables[5]
    player_angle = state.game_variables[7]

    # Collect visible object IDs rendered on screen by the 3D rasterizer
    visible_ids: Optional[Set[int]] = None
    if hasattr(state, "labels") and state.labels is not None:
        visible_ids = {
            l.object_id for l in state.labels
            if l.object_id != 0 and l.width > 0 and l.height > 0
        }

    found = False
    best_bearing = 0.0
    min_dist_sq = float("inf")

    # Pass 1: Try to locate the specific target chosen by the LLM (if visible)
    if target_name != "none":
        for obj in state.objects:
            # Skip local player
            if obj.name == "DoomPlayer" and (
                obj.id == 0
                or (abs(obj.position_x - player_x) < 2.0 and abs(obj.position_y - player_y) < 2.0)
            ):
                continue

            if obj.name == target_name or (target_name == "DoomPlayer" and "Player" in obj.name):
                # Must be rendered on screen
                if visible_ids is not None and obj.id not in visible_ids:
                    continue

                dx = obj.position_x - player_x
                dy = obj.position_y - player_y
                dist_sq = dx * dx + dy * dy
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    absolute = math.degrees(math.atan2(dy, dx))
                    best_bearing = (absolute - player_angle + 180) % 360 - 180
                    found = True

    # Pass 2: Fallback to closest visible hostile in line of sight (zero hesitation!)
    if not found and visible_ids:
        for obj in state.objects:
            if obj.name == "DoomPlayer" and (
                obj.id == 0
                or (abs(obj.position_x - player_x) < 2.0 and abs(obj.position_y - player_y) < 2.0)
            ):
                continue

            if obj.id in visible_ids and (obj.name in ENEMY_CLASSES or "Player" in obj.name):
                dx = obj.position_x - player_x
                dy = obj.position_y - player_y
                dist_sq = dx * dx + dy * dy
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    absolute = math.degrees(math.atan2(dy, dx))
                    best_bearing = (absolute - player_angle + 180) % 360 - 180
                    found = True

    return found, best_bearing


def resolve_dag(
    decision: JevResponse, state: Any
) -> Tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
    """
    Translate typed API decisions into a binary ViZDoom action tuple.

    Order (matches available_buttons in custom_scenario.cfg):
        (ATTACK, MOVE_FORWARD, MOVE_BACKWARD, MOVE_LEFT, MOVE_RIGHT,
         TURN_LEFT, TURN_RIGHT, JUMP)
    """
    attack = move_fwd = move_back = move_left = move_right = False
    turn_left = turn_right = jump = False

    # ── 1. Aiming: geometric bearing overrides API rotation suggestion ───────
    target_name = decision.target.value
    has_target, target_bearing = _get_target_bearing(target_name, state)

    if has_target:
        # Geometry is ground-truth; use it for fine crosshair tracking
        if target_bearing > 2.0:
            turn_left  = True
        elif target_bearing < -2.0:
            turn_right = True
    else:
        # No visible target in line-of-sight → follow the API's rotation suggestion
        rot = decision.rotation.value
        if rot == "turn_left":
            turn_left  = True
        elif rot == "turn_right":
            turn_right = True

    # ── 2. Movement (direct from API `movement` question) ───────────────────
    mv = decision.movement.value
    if mv == "forward":
        move_fwd   = True
    elif mv == "backward":
        move_back  = True
    elif mv == "left":
        move_left  = True
    elif mv == "right":
        move_right = True
    # "none" → all False (hold position)

    # ── 3. Jump ─────────────────────────────────────────────────────────────
    if decision.jump.value and decision.jump.confidence > 0.60:
        jump = True

    # ── 4. Trigger lock & Aggressive Firing (Zero Hesitation!) ──────────────
    # A) Continuous spam firing when requested (> 0.70 confidence)
    # B) Instant fire whenever an enemy is centered near crosshair (<= 15 deg)
    # C) Fire when tracking enemy and engaging (<= 25 deg)
    firing_conf = decision.firing.confidence

    if firing_conf > 0.70:
        attack = True
    elif has_target and abs(target_bearing) <= 15.0:
        # Crosshair is on a visible enemy: SHOOT IMMEDIATELY, NO HESITATION!
        attack = True
    elif has_target and abs(target_bearing) <= 25.0 and (firing_conf >= 0.25 or decision.macro_goal.value == "engage"):
        attack = True
    elif not has_target and firing_conf >= 0.50:
        attack = True

    return (attack, move_fwd, move_back, move_left, move_right, turn_left, turn_right, jump)
