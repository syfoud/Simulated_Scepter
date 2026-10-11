from collections.abc import Sequence

RESOURCE_INHERITANCE_INVESTMENT = "轮回不止"
DEFAULT_INVESTMENT_INDEX = 1
SAFE_SIDE_INDEX = 0


def choose_fallback_investment(
    texts: Sequence[str],
    icon_presence: Sequence[bool],
) -> int:
    """Choose the default option without overwriting inherited resources."""
    if len(texts) <= DEFAULT_INVESTMENT_INDEX:
        return SAFE_SIDE_INDEX

    middle_has_icon = (
        len(icon_presence) > DEFAULT_INVESTMENT_INDEX
        and icon_presence[DEFAULT_INVESTMENT_INDEX]
    )
    if (
        not middle_has_icon
        and RESOURCE_INHERITANCE_INVESTMENT in texts[DEFAULT_INVESTMENT_INDEX]
    ):
        return SAFE_SIDE_INDEX

    return DEFAULT_INVESTMENT_INDEX
