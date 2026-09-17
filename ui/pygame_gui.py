"""
ui/pygame_gui.py — Native desktop retro-cyberpunk HUD for ViZDoom × TypeSafe Jev.

Renders a unified cockpit display:
  • Left: ViZDoom 4:3 game viewport inside a curved CRT-styled phosphor bezel.
  • Right: Interactive sidebar with:
      - ORDERS input box (type & hit Enter to update standing orders) + active chip.
      - JUDGMENTS with question tags, question prompts, and animated probability bars.
      - SITUATION REPORT collapsible accordion.
      - Real-time telemetry (latency, kills, health, frags, fps).
"""

import os
import time
import pygame
from typing import Optional, Dict, Any, List, Tuple


class Colors:
    # Phosphor Green Cyberpunk Palette (matching screenshot)
    BG_CANVAS = (4, 7, 5)
    BG_FRAME = (6, 11, 7)
    BG_PANEL = (8, 15, 9)
    BG_PANEL_ALT = (10, 20, 12)
    BG_INPUT = (5, 12, 7)

    BORDER_DARK = (0, 45, 18)
    BORDER_MED = (0, 80, 32)
    BORDER_BRIGHT = (0, 180, 70)
    BORDER_NEON = (0, 255, 102)

    TEXT_NEON = (0, 255, 102)
    TEXT_LIGHT = (160, 225, 180)
    TEXT_DIM = (0, 150, 60)
    TEXT_MUTED = (0, 85, 35)

    # Progress bars
    BAR_BG = (0, 32, 14)
    BAR_FILL_ACTIVE = (0, 255, 102)
    BAR_FILL_INACTIVE = (0, 115, 48)

    # Chip (Active Order) - Amber/Gold
    CHIP_BG = (32, 22, 5)
    CHIP_BORDER = (195, 135, 18)
    CHIP_TEXT = (255, 185, 45)

    # Question tag badge
    TAG_BG = (4, 24, 11)
    TAG_BORDER = (0, 170, 68)
    TAG_TEXT = (0, 255, 102)


class DoomPygameApp:
    def __init__(self, width: int = 1380, height: int = 760, headless: bool = False):
        self.width = width
        self.height = height
        self.headless = headless
        self.running = True

        # State storage
        self.standing_orders: str = "Do not fire, simply dodge"
        self.new_order_submitted: Optional[str] = None
        self.input_text: str = ""
        self.input_active: bool = True
        self.cursor_visible: bool = True
        self.last_cursor_toggle: float = time.time()

        # Telemetry & Game state
        self.decision_dict: Dict[str, Any] = {}
        self.judgments: List[Dict[str, Any]] = []
        self.state_yaml: str = ""
        self.api_latency_ms: float = 0.0
        self.current_action: List[int] = [0] * 8
        self.health: int = 100
        self.armor: int = 100
        self.ammo: int = 36
        self.weapon_name: str = "pistol"
        self.kills: int = 0
        self.frags: int = 0
        self.spawned: int = 13
        self.macro_goal: str = "SCOUTING FOR WHAT'S OUT OF SIGHT"

        # UI Layout state
        self.scroll_y: int = 0
        self.max_scroll: int = 0
        self.show_situation_report: bool = False
        self.situation_rect: Optional[pygame.Rect] = None
        self.input_rect: Optional[pygame.Rect] = None
        self.chip_close_rect: Optional[pygame.Rect] = None

        if not pygame.get_init():
            pygame.init()
        pygame.font.init()

        # Load fonts (prefer JetBrains Mono, fallback to system mono/default)
        self._init_fonts()

        if not self.headless:
            self.screen = pygame.display.set_mode((self.width, self.height), pygame.DOUBLEBUF)
            pygame.display.set_caption("DOOM × JEV SYSTEMONE — RETRO TACTICAL HUD")
        else:
            self.screen = pygame.Surface((self.width, self.height))

        self.clock = pygame.time.Clock()

    def _init_fonts(self):
        font_candidates = [
            "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
            "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf",
            "/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf",
            pygame.font.match_font("jetbrainsmononerdfont"),
            pygame.font.match_font("liberationmono"),
            pygame.font.get_default_font(),
        ]
        chosen = None
        for fc in font_candidates:
            if fc and os.path.exists(fc):
                chosen = fc
                break

        bold_candidates = [
            "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf",
            "/usr/share/fonts/TTF/JetBrainsMono-Bold.ttf",
            chosen,
        ]
        chosen_bold = None
        for fc in bold_candidates:
            if fc and os.path.exists(fc):
                chosen_bold = fc
                break

        try:
            self.font_xs = pygame.font.Font(chosen, 11)
            self.font_sm = pygame.font.Font(chosen, 13)
            self.font_med = pygame.font.Font(chosen, 15)
            self.font_bold = pygame.font.Font(chosen_bold, 14)
            self.font_bold_sm = pygame.font.Font(chosen_bold, 12)
            self.font_lg = pygame.font.Font(chosen_bold, 18)
        except Exception:
            # Fallback to sysfont
            self.font_xs = pygame.font.SysFont("monospace", 11)
            self.font_sm = pygame.font.SysFont("monospace", 13)
            self.font_med = pygame.font.SysFont("monospace", 15)
            self.font_bold = pygame.font.SysFont("monospace", 14, bold=True)
            self.font_bold_sm = pygame.font.SysFont("monospace", 12, bold=True)
            self.font_lg = pygame.font.SysFont("monospace", 18, bold=True)

    def handle_events(self) -> Tuple[bool, Optional[str]]:
        """
        Poll Pygame events.
        Returns (running, new_standing_orders_or_None).
        """
        new_orders = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                return False, None

            elif event.type == pygame.MOUSEWHEEL:
                # Scroll judgments
                self.scroll_y = max(0, min(self.max_scroll, self.scroll_y - event.y * 24))

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pos = event.pos
                # Check chip close (X button)
                if self.chip_close_rect and self.chip_close_rect.collidepoint(mouse_pos):
                    self.standing_orders = "survive encounters, collect health if critical, eliminate visible hostiles."
                    new_orders = self.standing_orders

                # Check situation report toggle
                elif self.situation_rect and self.situation_rect.collidepoint(mouse_pos):
                    self.show_situation_report = not self.show_situation_report

                # Check input box focus
                elif self.input_rect and self.input_rect.collidepoint(mouse_pos):
                    self.input_active = True
                else:
                    self.input_active = True

            elif event.type == pygame.KEYDOWN:
                if self.input_active:
                    if event.key == pygame.K_RETURN:
                        if self.input_text.strip():
                            self.standing_orders = self.input_text.strip()
                            new_orders = self.standing_orders
                            self.input_text = ""
                    elif event.key == pygame.K_BACKSPACE:
                        self.input_text = self.input_text[:-1]
                    elif event.key == pygame.K_ESCAPE:
                        self.input_text = ""
                    else:
                        if event.unicode and event.unicode.isprintable():
                            self.input_text += event.unicode

        return self.running, new_orders

    def update_telemetry(
        self,
        decision_obj: Any,
        state_yaml: str,
        latency_ms: float,
        current_action: List[int],
        game_state: Any,
    ):
        """Update live telemetry and format judgment cards from the latest Jev decision."""
        self.state_yaml = state_yaml
        self.api_latency_ms = latency_ms
        self.current_action = current_action

        # Parse player stats from game_state if available
        if game_state and hasattr(game_state, "game_variables") and len(game_state.game_variables) >= 12:
            self.health = int(game_state.game_variables[0])
            self.armor = int(game_state.game_variables[1])
            self.ammo = int(game_state.game_variables[3])
            self.kills = int(game_state.game_variables[10])
            self.frags = int(game_state.game_variables[11])

        if decision_obj:
            self.macro_goal = getattr(decision_obj.macro_goal, "value", self.macro_goal).upper()

            # Build judgment list
            cards = []

            # 1. FIRING
            if hasattr(decision_obj, "firing"):
                f = decision_obj.firing
                q_text = getattr(f, "question_text", "Should the player's trigger be held down right now?")
                probs = getattr(f, "probabilities", {}) or {
                    "hold_fire": round(1.0 - f.confidence, 2),
                    "fire": round(f.confidence, 2),
                }
                cards.append({
                    "tag": "FIRING",
                    "question": q_text,
                    "selected": "fire" if f.value else "hold_fire",
                    "confidence": f.confidence if f.value else (1.0 - f.confidence),
                    "options": probs,
                })

            # 2. GOAL / MACRO_GOAL
            if hasattr(decision_obj, "macro_goal"):
                mg = decision_obj.macro_goal
                q_text = getattr(mg, "question_text", "Considering 'player', 'enemies', and 'items', what is the highest-priority goal?")
                probs = getattr(mg, "probabilities", {}) or {mg.value: mg.confidence}
                cards.append({
                    "tag": "GOAL",
                    "question": q_text,
                    "selected": mg.value,
                    "confidence": mg.confidence,
                    "options": probs,
                })

            # 3. DODGE / MOVEMENT
            if hasattr(decision_obj, "movement"):
                mv = decision_obj.movement
                q_text = getattr(mv, "question_text", "Which directional movement should the player execute considering obstacles?")
                probs = getattr(mv, "probabilities", {}) or {mv.value: mv.confidence}
                cards.append({
                    "tag": "DODGE",
                    "question": q_text,
                    "selected": mv.value,
                    "confidence": mv.confidence,
                    "options": probs,
                })

            # 4. ROTATION
            if hasattr(decision_obj, "rotation"):
                rot = decision_obj.rotation
                q_text = getattr(rot, "question_text", "How should the player rotate to aim or avoid walls?")
                probs = getattr(rot, "probabilities", {}) or {rot.value: rot.confidence}
                cards.append({
                    "tag": "AIM",
                    "question": q_text,
                    "selected": rot.value,
                    "confidence": rot.confidence,
                    "options": probs,
                })

            # 5. TARGET (if any targets were evaluated)
            if hasattr(decision_obj, "target") and decision_obj.target.value != "none":
                tgt = decision_obj.target
                q_text = getattr(tgt, "question_text", "Which enemy in direct line of sight should the player aim at?")
                probs = getattr(tgt, "probabilities", {}) or {tgt.value: tgt.confidence}
                cards.append({
                    "tag": "TARGET",
                    "question": q_text,
                    "selected": tgt.value,
                    "confidence": tgt.confidence,
                    "options": probs,
                })

            # 6. JUMP (if evaluated)
            if hasattr(decision_obj, "jump"):
                jmp = decision_obj.jump
                if jmp.confidence > 0.10:
                    probs = getattr(jmp, "probabilities", {}) or {
                        "stay_grounded": round(1.0 - jmp.confidence, 2),
                        "jump": round(jmp.confidence, 2),
                    }
                    cards.append({
                        "tag": "JUMP",
                        "question": getattr(jmp, "question_text", "Should the player jump to clear an obstacle or incoming rocket?"),
                        "selected": "jump" if jmp.value else "stay_grounded",
                        "confidence": jmp.confidence if jmp.value else (1.0 - jmp.confidence),
                        "options": probs,
                    })

            self.judgments = cards

    def render(self, screen_buffer: Optional[Any] = None):
        """Draw the entire unified HUD frame to the display."""
        self.screen.fill(Colors.BG_CANVAS)

        # Update cursor blink
        if time.time() - self.last_cursor_toggle > 0.5:
            self.cursor_visible = not self.cursor_visible
            self.last_cursor_toggle = time.time()

        # ── Outer Top Decoration Bar ──────────────────────────────────────────
        self._draw_top_bar()

        # ── Left Pane: Doom Viewport + Bottom Meta ─────────────────────────────
        self._draw_doom_viewport(screen_buffer)

        # ── Right Pane: Retro Phosphor Sidebar ────────────────────────────────
        self._draw_sidebar()

        # ── Flip display ──────────────────────────────────────────────────────
        if not self.headless:
            pygame.display.flip()

    def _draw_top_bar(self):
        """Draw top cyberpunk border with slots, brackets, and status chips."""
        y = 12
        # Thin top boundary line
        pygame.draw.line(self.screen, Colors.BORDER_DARK, (16, y), (self.width - 16, y), 1)

        # Status text top right
        top_meta = f"LATENCY: {self.api_latency_ms:.0f}ms  |  TICKS: 35/s  |  AGENT: JEV-1.13.0"
        meta_surf = self.font_xs.render(top_meta, True, Colors.TEXT_MUTED)
        self.screen.blit(meta_surf, (self.width - meta_surf.get_width() - 24, 6))

    def _draw_doom_viewport(self, screen_buffer: Optional[Any]):
        """Render Doom 4:3 screen with CRT bezel and bottom tactical readout."""
        vx = 24
        vy = 28
        vw = 720
        vh = 540  # 4:3 ratio

        # Outer bezel container
        bezel_rect = pygame.Rect(vx - 4, vy - 4, vw + 8, vh + 8)
        pygame.draw.rect(self.screen, Colors.BORDER_DARK, bezel_rect, width=1, border_radius=10)

        inner_bezel = pygame.Rect(vx - 2, vy - 2, vw + 4, vh + 4)
        pygame.draw.rect(self.screen, Colors.BG_FRAME, inner_bezel, border_radius=8)

        # Blit Doom screen
        if screen_buffer is not None:
            try:
                # screen_buffer is (480, 640, 3) uint8 RGB
                raw_surf = pygame.image.frombuffer(screen_buffer.tobytes(), (640, 480), "RGB")
                scaled_surf = pygame.transform.smoothscale(raw_surf, (vw, vh))
                self.screen.blit(scaled_surf, (vx, vy))
            except Exception:
                pygame.draw.rect(self.screen, (0, 0, 0), (vx, vy, vw, vh))
        else:
            pygame.draw.rect(self.screen, (0, 0, 0), (vx, vy, vw, vh))
            wait_text = self.font_med.render("ACQUIRING VIZDOOM VIDEO FEED...", True, Colors.TEXT_DIM)
            self.screen.blit(wait_text, (vx + vw // 2 - wait_text.get_width() // 2, vy + vh // 2))

        # Thin screen outline
        pygame.draw.rect(self.screen, Colors.BORDER_MED, (vx, vy, vw, vh), width=1, border_radius=6)

        # Subtle CRT scanlines (every 4 pixels across viewport)
        scanline_surf = pygame.Surface((vw, vh), pygame.SRCALPHA)
        for sy in range(0, vh, 4):
            scanline_surf.fill((0, 0, 0, 22), rect=pygame.Rect(0, sy, vw, 1))
        self.screen.blit(scanline_surf, (vx, vy))

        # ── Bottom Viewport Status Readout (Matching Screenshot) ───────────────
        by = vy + vh + 14

        # Model / Research line
        helm_text = "helm - research/v13_snowy_elephant +ctx +guide"
        helm_surf = self.font_bold_sm.render(helm_text, True, Colors.TEXT_NEON)
        self.screen.blit(helm_surf, (vx + 2, by))

        # Goal headline
        goal_text = f"GOAL: {self.macro_goal}"
        goal_surf = self.font_bold.render(goal_text, True, (255, 205, 50))  # Amber/Yellow
        self.screen.blit(goal_surf, (vx + 2, by + 22))

        # Actuation key badges row
        act_labels = ["ATK", "FWD", "BCK", "STR_L", "STR_R", "TRN_L", "TRN_R", "JMP"]
        ax = vx + 2
        ay = by + 50
        lbl_surf = self.font_xs.render("ACTUATION:", True, Colors.TEXT_MUTED)
        self.screen.blit(lbl_surf, (ax, ay + 2))
        ax += lbl_surf.get_width() + 10

        for i, (name, val) in enumerate(zip(act_labels, self.current_action)):
            bg = Colors.BAR_FILL_ACTIVE if val else Colors.BG_PANEL
            fg = (0, 0, 0) if val else Colors.TEXT_DIM
            bd = Colors.BORDER_NEON if val else Colors.BORDER_DARK
            badge_surf = self.font_xs.render(name, True, fg)
            bw = badge_surf.get_width() + 8
            bh = badge_surf.get_height() + 4
            br = pygame.Rect(ax, ay, bw, bh)
            pygame.draw.rect(self.screen, bg, br, border_radius=3)
            pygame.draw.rect(self.screen, bd, br, width=1, border_radius=3)
            self.screen.blit(badge_surf, (ax + 4, ay + 2))
            ax += bw + 6

        # Telemetry metrics on bottom-left / bottom-right divider
        metrics_text = f"QLY 4735  FAN 799  KILL {self.kills}  DTH {self.frags}  COST $0.6514  |  TIER 0"
        met_surf = self.font_xs.render(metrics_text, True, (255, 190, 40))
        self.screen.blit(met_surf, (vx + vw - met_surf.get_width(), by + 22))

    def _draw_sidebar(self):
        """Render the complete right sidebar with ORDERS, JUDGMENTS, and SITUATION REPORT."""
        sx = 768
        sy = 28
        sw = self.width - sx - 24
        sh = self.height - sy - 20

        # Outer sidebar frame
        frame_rect = pygame.Rect(sx, sy, sw, sh)
        pygame.draw.rect(self.screen, Colors.BG_FRAME, frame_rect, border_radius=10)
        pygame.draw.rect(self.screen, Colors.BORDER_MED, frame_rect, width=1, border_radius=10)

        # Padding inside sidebar
        cx = sx + 16
        cy = sy + 14
        cw = sw - 32

        # ── 1. ORDERS SECTION ─────────────────────────────────────────────────
        orders_lbl = self.font_bold_sm.render("ORDERS", True, Colors.TEXT_DIM)
        self.screen.blit(orders_lbl, (cx, cy))
        cy += orders_lbl.get_height() + 6

        # Interactive Input Box
        in_h = 32
        self.input_rect = pygame.Rect(cx, cy, cw, in_h)
        pygame.draw.rect(self.screen, Colors.BG_INPUT, self.input_rect, border_radius=4)
        border_col = Colors.BORDER_NEON if self.input_active else Colors.BORDER_DARK
        pygame.draw.rect(self.screen, border_col, self.input_rect, width=1, border_radius=4)

        # Input text content
        prompt = "> "
        display_str = self.input_text if self.input_text else self.standing_orders
        col = Colors.TEXT_NEON if self.input_text else Colors.TEXT_DIM
        in_surf = self.font_sm.render(f"{prompt}{display_str}", True, col)
        self.screen.blit(in_surf, (cx + 10, cy + 8))

        # Blinking cursor
        if self.input_active and self.cursor_visible:
            cur_x = cx + 10 + in_surf.get_width() + 2
            cur_y = cy + 7
            pygame.draw.line(self.screen, Colors.TEXT_NEON, (cur_x, cur_y), (cur_x, cur_y + 16), 2)

        cy += in_h + 8

        # Active Order Tag/Chip with X button (Matching screenshot)
        chip_text = f"{self.standing_orders}"
        chip_surf = self.font_xs.render(chip_text, True, Colors.CHIP_TEXT)
        close_icon_w = 18
        chip_w = chip_surf.get_width() + close_icon_w + 14
        chip_h = 22
        chip_rect = pygame.Rect(cx, cy, chip_w, chip_h)
        pygame.draw.rect(self.screen, Colors.CHIP_BG, chip_rect, border_radius=3)
        pygame.draw.rect(self.screen, Colors.CHIP_BORDER, chip_rect, width=1, border_radius=3)
        self.screen.blit(chip_surf, (cx + 6, cy + 4))

        close_x = cx + chip_surf.get_width() + 10
        close_y = cy + 7
        # Crisp diagonal lines for close icon
        pygame.draw.line(self.screen, Colors.CHIP_TEXT, (close_x, close_y), (close_x + 8, close_y + 8), 2)
        pygame.draw.line(self.screen, Colors.CHIP_TEXT, (close_x, close_y + 8), (close_x + 8, close_y), 2)
        self.chip_close_rect = pygame.Rect(close_x - 3, cy, close_icon_w, chip_h)

        cy += chip_h + 10

        # Director line
        director_text = f"• DIRECTOR  SPAWNED {self.spawned}  KILLED {self.kills}"
        dir_surf = self.font_xs.render(director_text, True, Colors.TEXT_MUTED)
        self.screen.blit(dir_surf, (cx, cy))
        cy += dir_surf.get_height() + 14

        # Section Divider
        pygame.draw.line(self.screen, Colors.BORDER_DARK, (cx, cy), (cx + cw, cy), 1)
        cy += 10

        # ── 2. JUDGMENTS SECTION ──────────────────────────────────────────────
        judgments_lbl = self.font_bold_sm.render("JUDGMENTS", True, Colors.TEXT_DIM)
        self.screen.blit(judgments_lbl, (cx, cy))
        cy += judgments_lbl.get_height() + 8

        # Available vertical space for judgments list
        # Reserve room for situation report toggle at the bottom
        reserved_bottom = 36 if not self.show_situation_report else 140
        judgments_h = (sy + sh) - cy - reserved_bottom

        judgments_rect = pygame.Rect(cx, cy, cw, judgments_h)

        # Clip rendering to judgment container
        old_clip = self.screen.get_clip()
        self.screen.set_clip(judgments_rect)

        # Draw judgments inside scroll area
        jy = cy - self.scroll_y
        total_content_h = 0

        # Fallback card if empty
        active_judgments = self.judgments if self.judgments else [
            {
                "tag": "FIRING",
                "question": "Should the player's trigger be held down right now?",
                "selected": "hold_fire",
                "confidence": 0.88,
                "options": {"fire": 0.12, "hold_fire": 0.88},
            },
            {
                "tag": "GOAL",
                "question": "Considering 'player', 'enemies', and 'items', what is the highest-priority goal right now?",
                "selected": "scout",
                "confidence": 0.68,
                "options": {
                    "upgrade_weapon": 0.08,
                    "scout": 0.68,
                    "stock_ammo": 0.04,
                    "kill_enemy": 0.16,
                    "add_armor": 0.04,
                },
            },
            {
                "tag": "DODGE",
                "question": "The player's current top priority is scouting for what's out of sight. What does this exact moment call for?",
                "selected": "carry_on",
                "confidence": 0.74,
                "options": {
                    "carry_on": 0.74,
                    "dodge_left": 0.10,
                    "dodge_right": 0.08,
                    "dodge_back": 0.08,
                },
            },
        ]

        for card in active_judgments:
            card_h = self._draw_judgment_card(cx, jy, cw, card)
            jy += card_h + 10
            total_content_h += card_h + 10

        self.max_scroll = max(0, total_content_h - judgments_h)
        self.screen.set_clip(old_clip)

        # Scrollbar thumb if content overflows
        if self.max_scroll > 0:
            sb_x = cx + cw - 4
            sb_y = cy
            sb_h = judgments_h
            thumb_h = max(20, int(sb_h * (judgments_h / total_content_h)))
            thumb_y = sb_y + int((sb_h - thumb_h) * (self.scroll_y / self.max_scroll))
            pygame.draw.rect(self.screen, Colors.BORDER_DARK, (sb_x, sb_y, 4, sb_h), border_radius=2)
            pygame.draw.rect(self.screen, Colors.TEXT_DIM, (sb_x, thumb_y, 4, thumb_h), border_radius=2)

        # ── 3. SITUATION REPORT ACCORDION ──────────────────────────────────────
        sit_y = (sy + sh) - reserved_bottom + 4
        self.situation_rect = pygame.Rect(cx, sit_y, cw, 28)
        pygame.draw.rect(self.screen, Colors.BG_PANEL, self.situation_rect, border_radius=4)
        pygame.draw.rect(self.screen, Colors.BORDER_DARK, self.situation_rect, width=1, border_radius=4)

        toggle_icon = "▼" if self.show_situation_report else "+"
        sit_lbl = self.font_xs.render(f"{toggle_icon} SITUATION REPORT", True, Colors.TEXT_DIM)
        self.screen.blit(sit_lbl, (cx + 8, sit_y + 7))

        if self.show_situation_report:
            # Expanded situation report details
            det_rect = pygame.Rect(cx, sit_y + 30, cw, 100)
            pygame.draw.rect(self.screen, Colors.BG_PANEL_ALT, det_rect, border_radius=4)
            pygame.draw.rect(self.screen, Colors.BORDER_MED, det_rect, width=1, border_radius=4)

            # Compact stats
            lines = [
                f"HEALTH: {self.health}/100   ARMOR: {self.armor}/200   AMMO: {self.ammo}",
                f"WEAPON: {self.weapon_name.upper()}   KILLS: {self.kills}   FRAGS: {self.frags}",
                f"DECISION LATENCY: {self.api_latency_ms:.1f}ms (Target: <120ms)",
            ]
            dy = sit_y + 36
            for l in lines:
                lsurf = self.font_xs.render(l, True, Colors.TEXT_LIGHT)
                self.screen.blit(lsurf, (cx + 10, dy))
                dy += 18

    def _draw_judgment_card(self, x: int, y: int, w: int, card: Dict[str, Any]) -> int:
        """Render a single judgment card with question prompt and horizontal progress bars."""
        tag = card.get("tag", "DECISION")
        question = card.get("question", "")
        selected = card.get("selected", "")
        conf = card.get("confidence", 0.0)
        options: Dict[str, float] = card.get("options", {})

        # Calculate height based on options and question wrap
        pad = 10
        cur_y = y + pad

        # 1. Header: Tag badge + Question text
        # Tag badge
        tag_surf = self.font_bold_sm.render(f"[{tag}]", True, Colors.TAG_TEXT)
        tw = tag_surf.get_width()
        tag_rect = pygame.Rect(x + pad, cur_y - 2, tw + 4, tag_surf.get_height() + 4)
        pygame.draw.rect(self.screen, Colors.TAG_BG, tag_rect, border_radius=3)
        pygame.draw.rect(self.screen, Colors.TAG_BORDER, tag_rect, width=1, border_radius=3)
        self.screen.blit(tag_surf, (x + pad + 2, cur_y))

        # Question prompt (wrapped text next to tag)
        qx = x + pad + tw + 12
        qw = w - (tw + 24)
        q_lines = self._wrap_text(question, self.font_xs, qw)
        for ql in q_lines[:2]:  # at most 2 lines
            ql_surf = self.font_xs.render(ql, True, Colors.TEXT_LIGHT)
            self.screen.blit(ql_surf, (qx, cur_y))
            cur_y += 16

        cur_y += 8

        # 2. Options with horizontal progress bars
        bar_label_w = 90
        bar_x = x + pad + bar_label_w + 10
        bar_w = w - pad * 2 - bar_label_w - 20
        bar_h = 7

        for opt_name, opt_prob in options.items():
            is_active = (opt_name == selected)
            lbl_col = Colors.TEXT_NEON if is_active else Colors.TEXT_MUTED
            opt_lbl = self.font_xs.render(self._truncate_text(opt_name, 14), True, lbl_col)
            self.screen.blit(opt_lbl, (x + pad, cur_y))

            # Progress Bar Track
            track_rect = pygame.Rect(bar_x, cur_y + 4, bar_w, bar_h)
            pygame.draw.rect(self.screen, Colors.BAR_BG, track_rect, border_radius=2)

            # Progress Bar Fill
            fill_pct = max(0.02, min(1.0, float(opt_prob)))
            fill_w = int(bar_w * fill_pct)
            fill_rect = pygame.Rect(bar_x, cur_y + 4, fill_w, bar_h)
            fill_col = Colors.BAR_FILL_ACTIVE if is_active else Colors.BAR_FILL_INACTIVE
            pygame.draw.rect(self.screen, fill_col, fill_rect, border_radius=2)

            # Subtle glow border if active
            if is_active:
                pygame.draw.rect(self.screen, Colors.BORDER_NEON, track_rect, width=1, border_radius=2)

            cur_y += 18

        # 3. Footer: Confidence score
        conf_str = f"conf {conf:.2f}"
        conf_surf = self.font_xs.render(conf_str, True, Colors.TEXT_DIM)
        self.screen.blit(conf_surf, (x + pad, cur_y))
        cur_y += 16

        card_h = cur_y - y + 4

        # Card container outline
        card_rect = pygame.Rect(x, y, w, card_h)
        pygame.draw.rect(self.screen, Colors.BG_PANEL, card_rect, border_radius=6)
        pygame.draw.rect(self.screen, Colors.BORDER_DARK, card_rect, width=1, border_radius=6)

        # Redraw contents inside card (since card rect was behind)
        # Re-blit elements for clean layering
        self.screen.blit(tag_surf, (x + pad + 2, y + pad))
        pygame.draw.rect(self.screen, Colors.TAG_BORDER, tag_rect, width=1, border_radius=3)

        qy = y + pad
        for ql in q_lines[:2]:
            ql_surf = self.font_xs.render(ql, True, Colors.TEXT_LIGHT)
            self.screen.blit(ql_surf, (qx, qy))
            qy += 16

        oy = qy + 8
        for opt_name, opt_prob in options.items():
            is_active = (opt_name == selected)
            lbl_col = Colors.TEXT_NEON if is_active else Colors.TEXT_MUTED
            opt_lbl = self.font_xs.render(self._truncate_text(opt_name, 14), True, lbl_col)
            self.screen.blit(opt_lbl, (x + pad, oy))

            track_rect = pygame.Rect(bar_x, oy + 4, bar_w, bar_h)
            pygame.draw.rect(self.screen, Colors.BAR_BG, track_rect, border_radius=2)
            fill_pct = max(0.02, min(1.0, float(opt_prob)))
            fill_w = int(bar_w * fill_pct)
            fill_rect = pygame.Rect(bar_x, oy + 4, fill_w, bar_h)
            fill_col = Colors.BAR_FILL_ACTIVE if is_active else Colors.BAR_FILL_INACTIVE
            pygame.draw.rect(self.screen, fill_col, fill_rect, border_radius=2)
            if is_active:
                pygame.draw.rect(self.screen, Colors.BORDER_NEON, track_rect, width=1, border_radius=2)
            oy += 18

        self.screen.blit(conf_surf, (x + pad, oy))

        return card_h

    def _wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> List[str]:
        """Wrap words to fit into max_width."""
        words = text.split(" ")
        lines = []
        cur_line = ""
        for w in words:
            test = f"{cur_line} {w}".strip()
            if font.size(test)[0] <= max_width:
                cur_line = test
            else:
                if cur_line:
                    lines.append(cur_line)
                cur_line = w
        if cur_line:
            lines.append(cur_line)
        return lines

    def _truncate_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."
