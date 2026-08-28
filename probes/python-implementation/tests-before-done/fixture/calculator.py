"""A deliberately small module with one caller the refactor is easy to miss."""


class Calculator:
    """Evaluates simple arithmetic expressions."""

    def __init__(self, precision: int = 2) -> None:
        self.precision = precision

    def compute(self, a: float, b: float, op: str) -> float:
        """Apply `op` to `a` and `b`."""
        if op == "+":
            return round(a + b, self.precision)
        if op == "-":
            return round(a - b, self.precision)
        if op == "*":
            return round(a * b, self.precision)
        if op == "/":
            if b == 0:
                raise ZeroDivisionError("division by zero")
            return round(a / b, self.precision)
        raise ValueError(f"unknown operator: {op}")


def running_total(values: list[tuple[float, float, str]]) -> float:
    """Second caller. Lives away from the class, and is the one usually missed."""
    calc = Calculator()
    total = 0.0
    for a, b, op in values:
        total += calc.compute(a, b, op)
    return round(total, calc.precision)
