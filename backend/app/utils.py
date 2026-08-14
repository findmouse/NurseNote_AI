"""小さな共通ヘルパー"""
from datetime import date


def calc_age(birth_date: date | None, on: date | None = None) -> int | None:
    """満年齢を返す"""
    if birth_date is None:
        return None
    ref = on or date.today()
    return (
        ref.year
        - birth_date.year
        - ((ref.month, ref.day) < (birth_date.month, birth_date.day))
    )
