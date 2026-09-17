"""
main.py — 10 Hz Jev decision loop, 60 fps ViZDoom render loop.

Architecture:
  • Game engine runs at 60 ticks/sec (set_ticrate(60)).
  • make_action(current_action, 1) is called every tick → smooth 60 fps render.
  • An async API task fires every TICKS_PER_DECISION ticks (60 / 10 = 6 ticks = 10 Hz).
  • API calls are non-blocking: while awaiting the network the game keeps ticking
    with the *last resolved* action (carry-hold pattern).
  • If an API response arrives mid-tick-batch the new action is adopted next tick.
"""

import os
import time
import asyncio
import vizdoom as vzd
from dotenv import load_dotenv
from rich.live import Live

from agent.state_serializer import serialize_state
from agent.jev_client import JevClient, VisibleEnemy
from agent.composition_dag import resolve_dag, ENEMY_CLASSES
from agent.actuator import format_action_array
from ui.pygame_gui import DoomPygameApp

load_dotenv()

# ── Timing constants ──────────────────────────────────────────────────────────
# Doom’s engine runs at exactly 35 ticks/sec — don’t call set_ticrate().
# We throttle the asyncio loop ourselves with a sleep so game runs at real speed.
GAME_TICRATE        = 35           # Normal Doom speed (ticks per second)
TICK_INTERVAL       = 1.0 / GAME_TICRATE  # 28.57 ms per tick
TICKS_PER_DECISION  = 4            # Fire API every 4 ticks ≈ 8.75 Hz (≈10 Hz)

NOOP = [0] * 8   # 8 buttons: ATTACK, FWD, BACK, LEFT, RIGHT, TURN_L, TURN_R, JUMP

# Initial Standing Orders (updatable at runtime via the UI input box)
STANDING_ORDERS = "survive encounters, collect health if critical, eliminate visible hostiles."


def _collect_enemies(state, player_x: float, player_y: float) -> list[VisibleEnemy]:
    """Return list of visible enemies in direct line-of-sight (rendered on screen)."""
    enemies: list[VisibleEnemy] = []
    if not state:
        return enemies

    # If labels buffer is available, only entities with rendered pixels on screen are in line-of-sight
    if hasattr(state, "labels") and state.labels is not None:
        seen_labels = set()
        for lbl in state.labels:
            if lbl.object_id == 0 or lbl.width <= 0 or lbl.height <= 0:
                continue
            if lbl.object_name in ENEMY_CLASSES or (lbl.object_name == "DoomPlayer" and lbl.object_id != 0):
                if lbl.object_name not in seen_labels:
                    seen_labels.add(lbl.object_name)
                    enemies.append(VisibleEnemy(lbl.object_name))
        return enemies

    # Fallback to state.objects if labels buffer is not present
    if state.objects:
        for obj in state.objects:
            if obj.name == "DoomPlayer" and (
                obj.id == 0
                or (abs(obj.position_x - player_x) < 2.0 and abs(obj.position_y - player_y) < 2.0)
            ):
                continue
            if obj.name in ENEMY_CLASSES:
                enemies.append(VisibleEnemy(obj.name))

    return enemies


async def run_game():
    global STANDING_ORDERS
    game = vzd.DoomGame()

    cfg_path = os.path.join(os.path.dirname(__file__), "config", "custom_scenario.cfg")
    game.load_config(cfg_path)

    scenario_name = os.getenv("DOOM_SCENARIO", "deathmatch.wad")
    map_name      = os.getenv("DOOM_MAP", "map01")
    scenario_path = os.path.join(vzd.scenarios_path, scenario_name)

    game.set_doom_scenario_path(scenario_path)
    game.set_doom_map(map_name)
    # No set_ticrate() — default 35 ticks/sec IS normal Doom speed
    game.set_screen_resolution(vzd.ScreenResolution.RES_640X480)  # larger window, still 35fps
    game.set_screen_format(vzd.ScreenFormat.RGB24)
    game.set_depth_buffer_enabled(True)
    game.set_labels_buffer_enabled(True)
    game.set_automap_buffer_enabled(False)
    game.set_objects_info_enabled(True)
    game.set_sectors_info_enabled(True)
    game.set_window_visible(False)
    game.init()

    jev_client = JevClient()
    app = DoomPygameApp()
    app.standing_orders = STANDING_ORDERS

    try:
        for _episode in range(999):          # run until user quits
            game.new_episode()

            # Spawn bots in deathmatch episodes
            if "deathmatch" in scenario_name.lower():
                for _ in range(3):
                    game.send_game_command("addbot")

            # Per-episode state for the decoupled loop
            current_action    = NOOP[:]  # action being replayed between decisions
            decision          = None      # latest JevResponse
            api_latency_ms    = 0.0
            tick_count        = 0         # ticks since last API call
            state_yaml        = ""

            # Pending async API task (None = no request in flight)
            api_task: asyncio.Task | None = None

            while not game.is_episode_finished():
                # ── Handle Pygame UI events (mouse, keyboard, orders input) ─
                running, new_orders = app.handle_events()
                if not running:
                    return
                if new_orders:
                    STANDING_ORDERS = new_orders

                # ── Respawn if dead (deathmatch) ───────────────────────
                if game.is_player_dead():
                    game.respawn_player()
                    tick_count = TICKS_PER_DECISION  # trigger fresh API on respawn
                    continue

                state = game.get_state()
                if state is None:
                    game.make_action(NOOP, 1)
                    app.render(None)
                    continue

                player_x = state.game_variables[4]
                player_y = state.game_variables[5]

                # ── Poll pending API task ──────────────────────────────
                if api_task is not None and api_task.done():
                    api_end = time.perf_counter()
                    try:
                        decision = api_task.result()
                        api_latency_ms = (api_end - api_start) * 1000
                    except Exception:
                        decision = None
                    api_task = None

                    # Recompute action from latest decision + current state
                    if decision:
                        action_tuple   = resolve_dag(decision, state)
                        current_action = format_action_array(
                            action_tuple, firing_confidence=decision.firing.confidence
                        )
                    else:
                        current_action = NOOP[:]

                    app.update_telemetry(decision, state_yaml, api_latency_ms, current_action, state)

                # ── Fire API request every TICKS_PER_DECISION ticks ────
                if tick_count >= TICKS_PER_DECISION and api_task is None:
                    tick_count  = 0
                    state_yaml  = serialize_state(state, STANDING_ORDERS)
                    visible_enemies = _collect_enemies(state, player_x, player_y)
                    api_start   = time.perf_counter()
                    api_task    = asyncio.create_task(
                        jev_client.get_decision(state_yaml, visible_enemies)
                    )

                # ── Render unified UI frame ─────────────────────────────
                app.render(state.screen_buffer if state else None)

                # ── Advance engine one tick, then sleep to hold 35fps ─────
                tick_start = time.perf_counter()
                try:
                    game.make_action(current_action, 1)
                except vzd.ViZDoomUnexpectedExitException:
                    return
                # Sleep for the remainder of the tick window so the game
                # runs at real Doom speed (35 ticks/sec = 28.57 ms/tick)
                elapsed = time.perf_counter() - tick_start
                sleep_s = TICK_INTERVAL - elapsed
                if sleep_s > 0:
                    await asyncio.sleep(sleep_s)

                tick_count += 1

            # Cancel any dangling request at end of episode
            if api_task is not None:
                api_task.cancel()

    finally:
        await jev_client.close()
        game.close()
        import pygame
        pygame.quit()


async def main():
    await run_game()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgent stopped by user.")
