"""Typed amounts, including simple arithmetic.

The server twin of ``assets/javascript/common/amount.js``. With JavaScript on,
an amount field swaps a formula ("45.20+12.80", "3*19.99") for its result
before anything is posted; this is what makes the no-JS form paths accept the
same input, so a ``<noscript>`` fallback is never stricter than the page.

Evaluated by a small recursive-descent parser over ``Decimal`` -- never
``eval`` -- so ``+``/``-``/``*`` are exact and ``/`` is exact to 28 digits
before the result is rounded to cents.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation

CENT = Decimal("0.01")
MAX_EXPRESSION_LENGTH = 200

_TOKEN = re.compile(r"\d+\.?\d*|\.\d+|[-+*/()]")
_OPERATOR_AFTER_OPERAND = re.compile(r"[\d.)][-+*/]")


def _normalize(text):
    text = re.sub(r"[\s   ]", "", text)
    text = re.sub(r"[$€£,]", "", text)
    text = text.replace("−", "-").replace("÷", "/")
    return re.sub(r"[x×X]", "*", text)


def _parse_plain(text):
    """A plain number: "$1,234.56", "(45.50)" for a negative, "-12". None otherwise."""
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    if not re.fullmatch(r"\d+\.?\d*|\.\d+", text):
        return None
    value = Decimal(text)
    return -value if negative else value


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.pos += 1
        return token

    def expr(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.term()
            value = value + right if op == "+" else value - right
        return value

    def term(self):
        value = self.factor()
        while self.peek() in ("*", "/"):
            op = self.take()
            right = self.factor()
            if op == "/" and right == 0:
                raise DivisionByZero
            value = value * right if op == "*" else value / right
        return value

    def factor(self):
        token = self.take()
        if token == "-":
            return -self.factor()
        if token == "+":
            return self.factor()
        if token == "(":
            value = self.expr()
            if self.take() != ")":
                raise ValueError("unbalanced parentheses")
            return value
        if token is None or not any(c.isdigit() for c in token):
            raise ValueError("expected a number")
        return Decimal(token)


def evaluate_amount(value):
    """A typed amount -- plain number or formula -- as a ``Decimal`` rounded to
    cents, or None when it is neither. Blank is None; callers decide what blank
    means."""
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP) if value.is_finite() else None
    text = _normalize(str(value if value is not None else ""))
    if not text or len(text) > MAX_EXPRESSION_LENGTH:
        return None

    result = _parse_plain(text)
    if result is None:
        if not _OPERATOR_AFTER_OPERAND.search(text):
            return None
        tokens = _TOKEN.findall(text)
        if "".join(tokens) != text:
            return None
        parser = _Parser(tokens)
        try:
            result = parser.expr()
        except (ArithmeticError, InvalidOperation, ValueError):
            return None
        if parser.pos != len(tokens):
            return None
    if not result.is_finite():
        return None
    try:
        result = result.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:  # more digits than the context can hold
        return None
    return result + 0  # normalizes -0.00 to 0.00
