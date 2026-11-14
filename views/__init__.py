"""Streamlit pages. Each module exposes a render() function."""


def inr(value: float) -> str:
    """Format a number as Indian rupees with lakh/crore shorthand."""
    value = float(value or 0)
    if abs(value) >= 1e7:
        return f"₹{value / 1e7:.2f} Cr"
    if abs(value) >= 1e5:
        return f"₹{value / 1e5:.2f} L"
    return f"₹{value:,.0f}"
