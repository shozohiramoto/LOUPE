"""GUI-independent placement policy for LOUPE's comparison workbench."""

MAX_COMPARISON_VIEWS = 4


def horizontal_cells(count):
    """Every active panel occupies row 0, with equal column stretch."""
    if type(count) is not int or not 1 <= count <= MAX_COMPARISON_VIEWS:
        raise ValueError('View count must be 1–4')
    return [(0, col) for col in range(count)]


def density_for_window(count, width):
    """Select a toolbar density from the maximized/current window width.

    Width thresholds are progressive fallbacks for 4 panes on small screens.
    Image data and overlays are never downsampled in this layout helper.
    """
    horizontal_cells(count)
    if width <= 0:
        raise ValueError('Window width must be positive')
    available = max(0, width - 30 - 5 * (count - 1)) / count
    if available < 235:
        return 'ultra'
    if count >= 3 or available < 550:
        return 'compact'
    return 'normal'
