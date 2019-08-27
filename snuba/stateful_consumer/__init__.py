from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StateType(Enum):
    BOOTSTRAP = 0
    CONSUMING = 1
    SNAPSHOT_PAUSED = 2
    CATCHING_UP = 3
    FINISHED = 4


class StateCompletionEvent(Enum):
    CONSUMPTION_COMPLETED = 0
    SNAPSHOT_INIT_RECEIVED = 1
    SNAPSHOT_READY_RECEIVED = 2
    NO_SNAPSHOT = 3
    SNAPSHOT_CATCHUP_COMPLETED = 4


@dataclass
class StateData:
    """
    Represent the state information we pass from one
    state to the other.
    """
    snapshot_id: Optional[str]

    @classmethod
    def no_snapshot_state(cls):
        """
        Builds an empty StateData that represent a state where there is no
        snapshot to care about.
        """
        return StateData(None)