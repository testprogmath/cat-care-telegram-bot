"""Russian plural forms and the one-decimal numbers the messages use."""


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 100 in (11, 12, 13, 14):
        return many
    if n % 10 == 1:
        return one
    if n % 10 in (2, 3, 4):
        return few
    return many


def num(value: float) -> str:
    return f"{round(value, 1):g}"


def comma(value: float) -> str:
    return f"{value:g}".replace(".", ",")
