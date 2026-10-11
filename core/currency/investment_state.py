from collections import Counter, deque
from dataclasses import dataclass, field
from enum import StrEnum


class SelectionKind(StrEnum):
    NORMAL = "normal"
    IMMEDIATE_BONUS = "immediate_bonus"
    DELAYED_BONUS = "delayed_bonus"


@dataclass(frozen=True, slots=True)
class SelectionContext:
    kind: SelectionKind
    boundary: int


@dataclass(slots=True)
class InvestmentSelectionTracker:
    """Track normal and bonus investment choices across plane boundaries."""

    plane_count: int = 0
    _immediate_boundaries: deque[int] = field(default_factory=deque)
    _delayed_by_boundary: Counter[int] = field(default_factory=Counter)

    def reset(self) -> None:
        self.plane_count = 0
        self._immediate_boundaries.clear()
        self._delayed_by_boundary.clear()

    def begin_selection(self) -> SelectionContext:
        if self._immediate_boundaries:
            return SelectionContext(
                SelectionKind.IMMEDIATE_BONUS,
                self._immediate_boundaries[0],
            )

        boundary = self.plane_count
        if self._delayed_by_boundary[boundary] > 0:
            return SelectionContext(SelectionKind.DELAYED_BONUS, boundary)

        return SelectionContext(SelectionKind.NORMAL, boundary)

    def complete_selection(
        self,
        context: SelectionContext,
        grants_bonus: bool = False,
    ) -> None:
        expected = self.begin_selection()
        if context != expected:
            raise RuntimeError(
                f"Investment selection changed while processing: {context} != {expected}"
            )

        if context.kind == SelectionKind.IMMEDIATE_BONUS:
            self._immediate_boundaries.popleft()
        elif context.kind == SelectionKind.DELAYED_BONUS:
            self._delayed_by_boundary[context.boundary] -= 1
            if self._delayed_by_boundary[context.boundary] == 0:
                del self._delayed_by_boundary[context.boundary]
        else:
            self.plane_count += 1

        if grants_bonus:
            self._immediate_boundaries.append(context.boundary)
            self._delayed_by_boundary[context.boundary + 1] += 1

    @property
    def immediate_count(self) -> int:
        return len(self._immediate_boundaries)

    @property
    def delayed_count(self) -> int:
        return sum(self._delayed_by_boundary.values())

    def should_exit(self, exit_plane: int) -> bool:
        # Immediate choices block leaving the current screen. Delayed choices on a
        # future boundary are intentionally abandoned when the requested plane ends.
        return self.plane_count >= exit_plane and not self._immediate_boundaries
