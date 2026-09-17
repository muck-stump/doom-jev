import math
from typing import Dict, Any, List, Optional, Set, Tuple
import numpy as np

WEAPON_NAMES = {
    0: "fist",
    1: "fist",
    2: "pistol",
    3: "shotgun",
    4: "chaingun",
    5: "rocket_launcher",
    6: "plasma_rifle",
    7: "bfg9000",
}

ENEMY_NAMES = {
    "doomplayer", "imp", "zombieman", "shotgunguy", "chaingunguy", "demon", "spectre",
    "hellknight", "baronofhell", "cacodemon", "lostsoul", "revenant", "mancubus",
    "arachnotron", "archvile", "cyberdemon", "painelemental", "wolfensteinss"
}

WEAPON_PICKUP_KEYWORDS = [
    "supershotgun", "shotgun", "chaingun", "rocketlauncher",
    "plasmarifle", "bfg9000", "chainsaw"
]

HEALTH_KEYWORDS = ["medikit", "stimpack", "soulsphere", "megasphere", "healthbonus"]
ARMOR_KEYWORDS = ["greenarmor", "bluearmor", "armorbonus", "armor"]
AMMO_KEYWORDS = ["clipbox", "shellbox", "rocketbox", "cellpack", "clip", "shell", "cell", "ammo"]


def discretize_distance(distance: float) -> str:
    if distance < 64:
        return "contact"
    elif distance <= 255:
        return "close"
    elif distance <= 767:
        return "medium"
    else:
        return "far"


def discretize_bearing(bearing: float) -> str:
    if -15 <= bearing <= 15:
        return "dead ahead"
    elif 15 < bearing <= 45:
        return "ahead left"
    elif -45 <= bearing < -15:
        return "ahead right"
    elif 45 < bearing <= 135:
        return "left"
    elif -135 <= bearing < -45:
        return "right"
    else:
        return "behind"


def _ray_line_intersect(ox: float, oy: float, dx: float, dy: float,
                        x1: float, y1: float, x2: float, y2: float) -> Optional[float]:
    sx = x2 - x1
    sy = y2 - y1
    denom = dx * sy - dy * sx
    if abs(denom) < 1e-6:
        return None
    t = ((x1 - ox) * sy - (y1 - oy) * sx) / denom
    u = ((x1 - ox) * dy - (y1 - oy) * dx) / denom
    if t > 0 and 0.0 <= u <= 1.0:
        return t
    return None


def detect_walls(state: Any, px: float, py: float, p_angle: float) -> Dict[str, bool]:
    """Detect walls ahead, left, and right using depth buffer and blocking sector lines."""
    center_d = 255.0
    left_d = 255.0
    right_d = 255.0
    if hasattr(state, "depth_buffer") and state.depth_buffer is not None:
        try:
            h, w = state.depth_buffer.shape
            eye_t, eye_b = int(h * 0.35), int(h * 0.65)
            center_d = float(np.median(state.depth_buffer[eye_t:eye_b, int(w * 0.4):int(w * 0.6)]))
            left_d = float(np.median(state.depth_buffer[eye_t:eye_b, int(w * 0.1):int(w * 0.3)]))
            right_d = float(np.median(state.depth_buffer[eye_t:eye_b, int(w * 0.7):int(w * 0.9)]))
        except Exception:
            pass

    blocking_lines = []
    if hasattr(state, "sectors") and state.sectors:
        for sec in state.sectors:
            for line in sec.lines:
                if line.is_blocking:
                    blocking_lines.append(line)

    def cast_ray(angle_deg: float) -> float:
        rad = math.radians(angle_deg)
        dx, dy = math.cos(rad), math.sin(rad)
        min_dist = 9999.0
        for bl in blocking_lines:
            t = _ray_line_intersect(px, py, dx, dy, bl.x1, bl.y1, bl.x2, bl.y2)
            if t is not None and t < min_dist:
                min_dist = t
        return min_dist

    dist_ahead = cast_ray(p_angle)
    dist_left = cast_ray(p_angle + 40.0)
    dist_right = cast_ray(p_angle - 40.0)

    wall_ahead = (dist_ahead < 110.0) or (center_d <= 35.0)
    wall_left = (dist_left < 90.0) or (left_d <= 30.0)
    wall_right = (dist_right < 90.0) or (right_d <= 30.0)

    return {
        "wall_directly_ahead": wall_ahead,
        "wall_left": wall_left,
        "wall_right": wall_right,
    }


def serialize_state(state: Any, standing_orders: str) -> str:
    """
    Extracts coordinates from the ViZDoom state, calculates relative geometry,
    evaluates environmental wall detection and line-of-sight occlusion,
    and formats as a compact, low-latency YAML string (~300 tokens).
    """
    if not state:
        return ""

    player_x = state.game_variables[4]
    player_y = state.game_variables[5]
    player_angle = state.game_variables[7]

    health = state.game_variables[0]
    armor = state.game_variables[1]

    weapon_id = int(state.game_variables[2]) if len(state.game_variables) > 2 else 2
    weapon = WEAPON_NAMES.get(weapon_id, f"weapon_{weapon_id}")
    ammo_count = int(state.game_variables[3]) if len(state.game_variables) > 3 else 0

    # ── Wall detection ───────────────────────────────────────────────────────
    env_walls = detect_walls(state, player_x, player_y, player_angle)

    # ── Ground-truth Line-of-sight from engine rasterizer (labels buffer) ─────
    visible_label_ids: Set[int] = set()
    if hasattr(state, "labels") and state.labels is not None:
        visible_label_ids = {
            l.object_id for l in state.labels
            if l.object_id != 0 and l.width > 0 and l.height > 0
        }

    vis_enemies: List[Tuple[float, str]] = []
    occ_enemies: List[Tuple[float, str]] = []
    proj_list: List[Tuple[float, str]] = []
    wpn_pickups: List[Tuple[float, str]] = []
    vis_items: List[Tuple[float, str]] = []
    near_items: List[Tuple[float, str]] = []

    if state.objects:
        for obj in state.objects:
            # Skip local player
            if obj.name == "DoomPlayer" and (
                obj.id == 0
                or (abs(obj.position_x - player_x) < 2.0 and abs(obj.position_y - player_y) < 2.0)
            ):
                continue

            name_lower = obj.name.lower()

            # Ignore corpses and dead actors
            if name_lower.startswith("dead") or "gibbed" in name_lower or "corpse" in name_lower:
                continue

            dx = obj.position_x - player_x
            dy = obj.position_y - player_y
            distance = math.sqrt(dx * dx + dy * dy)

            absolute_angle = math.degrees(math.atan2(dy, dx))
            bearing = (absolute_angle - player_angle + 180) % 360 - 180

            dist_band = discretize_distance(distance)
            bearing_band = discretize_bearing(bearing)

            # Direct line of sight: physically rendered on screen
            is_visible = obj.id in visible_label_ids
            occluded_str = "false" if is_visible else "true"

            # ── 1. PROJECTILES (check first) ─────────────────────────────────
            is_projectile = (
                ("rocket" in name_lower and not any(w in name_lower for w in ["box", "launcher"])) or
                ("plasma" in name_lower and not any(w in name_lower for w in ["rifle", "cell", "gun"])) or
                any(p in name_lower for p in ["projectile", "fireball", "tracer", "ball"])
            )
            if is_projectile:
                entry = (
                    f"  - label: {obj.name}\n"
                    f"    distance: {int(distance)} ({dist_band})\n"
                    f"    bearing: {int(bearing)} deg ({bearing_band})"
                )
                proj_list.append((distance, entry))
                continue

            # ── 2. ENEMIES (MUST be checked before items; use exact matching to avoid 'imp' in 'stimpack') ──
            is_enemy = (
                obj.name in ENEMY_NAMES or
                name_lower in ENEMY_NAMES or
                ("player" in name_lower and "box" not in name_lower)
            )
            if is_enemy:
                entry = (
                    f"  - label: {obj.name}\n"
                    f"    distance: {int(distance)} ({dist_band})\n"
                    f"    bearing: {int(bearing)} deg ({bearing_band})\n"
                    f"    occluded: {occluded_str}"
                )
                if is_visible:
                    vis_enemies.append((distance, entry))
                else:
                    occ_enemies.append((distance, entry))
                continue

            # ── 3. WEAPON PICKUPS (dedicated category for collect_weapon) ────
            is_weapon_pickup = any(w in name_lower for w in WEAPON_PICKUP_KEYWORDS)
            if is_weapon_pickup:
                entry = (
                    f"  - label: {obj.name} (weapon)\n"
                    f"    distance: {int(distance)} ({dist_band})\n"
                    f"    bearing: {int(bearing)} deg ({bearing_band})\n"
                    f"    occluded: {occluded_str}"
                )
                wpn_pickups.append((distance, entry))
                continue

            # ── 4. GENERAL ITEMS (health, armor, ammo) ───────────────────────
            is_item = any(it in name_lower for it in (HEALTH_KEYWORDS + ARMOR_KEYWORDS + AMMO_KEYWORDS))
            if is_item:
                tag = ""
                if any(h in name_lower for h in HEALTH_KEYWORDS):
                    tag = " (health)"
                elif any(a in name_lower for a in ARMOR_KEYWORDS):
                    tag = " (armor)"
                elif any(m in name_lower for m in AMMO_KEYWORDS):
                    tag = " (ammo)"

                entry = (
                    f"  - label: {obj.name}{tag}\n"
                    f"    distance: {int(distance)} ({dist_band})\n"
                    f"    bearing: {int(bearing)} deg ({bearing_band})\n"
                    f"    occluded: {occluded_str}"
                )
                if is_visible:
                    vis_items.append((distance, entry))
                elif distance < 500:
                    near_items.append((distance, entry))

    # ── Compact filtering to keep prompt small (<400 tokens) and latency fast (<120ms) ──
    # Sort by distance
    vis_enemies.sort(key=lambda x: x[0])
    occ_enemies.sort(key=lambda x: x[0])
    proj_list.sort(key=lambda x: x[0])
    wpn_pickups.sort(key=lambda x: x[0])
    vis_items.sort(key=lambda x: x[0])
    near_items.sort(key=lambda x: x[0])

    # Select: ALL visible enemies + at most 3 closest occluded enemies
    final_enemies = [e[1] for e in vis_enemies] + [e[1] for e in occ_enemies[:3]]

    # Select: up to 3 closest weapons, up to 3 visible items, up to 3 nearby items
    final_items = (
        [w[1] for w in wpn_pickups[:3]] +
        [i[1] for i in vis_items[:3]] +
        [n[1] for n in near_items[:3]]
    )

    final_proj = [p[1] for p in proj_list[:3]]

    yaml_str = f"STANDING ORDERS:\n  - {standing_orders}\n"
    yaml_str += "SITUATION REPORT:\n"
    yaml_str += "player:\n"
    yaml_str += f"  health: {int(health)}/100\n"
    yaml_str += f"  armor: {int(armor)}/200\n"
    yaml_str += f"  weapon: {weapon}\n"
    yaml_str += f"  ammo: {ammo_count}\n"
    yaml_str += "  bearing_drift: 0 deg\n"

    # Wall detection block
    yaml_str += "environment:\n"
    yaml_str += f"  wall_directly_ahead: {'true' if env_walls['wall_directly_ahead'] else 'false'}\n"
    yaml_str += f"  wall_left: {'true' if env_walls['wall_left'] else 'false'}\n"
    yaml_str += f"  wall_right: {'true' if env_walls['wall_right'] else 'false'}\n"

    yaml_str += "enemies:\n"
    if final_enemies:
        yaml_str += "\n".join(final_enemies) + "\n"
    else:
        yaml_str += "  []\n"

    yaml_str += "items:\n"
    if final_items:
        yaml_str += "\n".join(final_items) + "\n"
    else:
        yaml_str += "  []\n"

    yaml_str += "incoming_threats:\n"
    if final_proj:
        yaml_str += "\n".join(final_proj) + "\n"
    else:
        yaml_str += "  []\n"

    return yaml_str
