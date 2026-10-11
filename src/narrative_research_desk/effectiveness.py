"""Fail-closed classification of product-effectiveness evidence."""


def classify_evidence(protocol_frozen: bool, completed: bool, n: int,
                      minimum_n: int, favorable: bool, risk_pass: bool) -> str:
    for name, value in (("protocol_frozen", protocol_frozen), ("completed", completed),
                        ("favorable", favorable), ("risk_pass", risk_pass)):
        if not isinstance(value, bool):
            raise ValueError(f"{name.upper()}_INVALID")
    if not isinstance(n, int) or isinstance(n, bool) or not isinstance(minimum_n, int) or isinstance(minimum_n, bool) or n < 0 or minimum_n < 1:
        raise ValueError("SAMPLE_SIZE_INVALID")
    if not completed:
        return "NOT_EVALUATED"
    if not protocol_frozen or n < minimum_n:
        return "INCONCLUSIVE"
    return "SUPPORTED" if favorable and risk_pass else "NOT_SUPPORTED"
