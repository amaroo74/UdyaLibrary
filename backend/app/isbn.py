import re


def clean_isbn(value: str) -> str:
    return re.sub(r"[^0-9X]", "", value.upper())


def _valid_isbn10(value: str) -> bool:
    return (
        len(value) == 10
        and value[:9].isdigit()
        and value[9] in "0123456789X"
        and sum((10 - index) * (10 if digit == "X" else int(digit)) for index, digit in enumerate(value)) % 11 == 0
    )


def _valid_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit() or not value.startswith(("978", "979")):
        return False
    checksum = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(value[:12]))
    return (10 - checksum % 10) % 10 == int(value[-1])


def normalize_isbn(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = clean_isbn(value)
    if _valid_isbn13(cleaned):
        return cleaned
    if _valid_isbn10(cleaned):
        isbn13_body = "978" + cleaned[:9]
        checksum = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(isbn13_body))
        return isbn13_body + str((10 - checksum % 10) % 10)
    return None
