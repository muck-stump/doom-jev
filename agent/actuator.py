from typing import Tuple, List, Optional, Any


def format_action_array(
    action_tuple: Tuple,
    firing_confidence: Optional[float] = None,
    decision: Optional[Any] = None,
) -> List[int]:
    """
    Converts the boolean tuple from the DAG into the integer array
    expected by ViZDoom's make_action.

    Order: [ATTACK, MOVE_FORWARD, MOVE_BACKWARD, MOVE_LEFT, MOVE_RIGHT,
            TURN_LEFT, TURN_RIGHT, JUMP]

    Spam Firing:
    Maps firing.confidence > 0.70 directly to the ATTACK button (button 0 = 1)
    to achieve continuous spam fire.
    """
    actions = [int(val) for val in action_tuple]

    conf = firing_confidence
    if conf is None and decision is not None:
        if hasattr(decision, "firing") and hasattr(decision.firing, "confidence"):
            conf = decision.firing.confidence
        elif isinstance(decision, dict) and "firing" in decision:
            firing_data = decision["firing"]
            if isinstance(firing_data, dict):
                conf = firing_data.get("confidence", 0.0)
            elif hasattr(firing_data, "confidence"):
                conf = firing_data.confidence

    if conf is not None and conf > 0.70:
        actions[0] = 1

    return actions
