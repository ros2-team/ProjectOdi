"""Bounded semantic-name aliases for memory retrieval, not object identity."""

# Only explicitly reviewed aliases are grouped. Do not strip arbitrary adjectives
# or use substring matches: e.g. a toy car must not become a real car.
NAME_GROUPS = (
    ('doll', 'plush doll', 'stuffed doll', 'plush toy', 'stuffed toy',
     'stuffed animal', 'plush animal', 'soft toy', '인형', '봉제 인형', '봉제인형'),
)


def normalize_name(name):
    return (name or '').strip().lower().replace('_', ' ').replace('-', ' ')


def memory_name_aliases(name):
    normalized = normalize_name(name)
    for group in NAME_GROUPS:
        if normalized in group:
            return group
    return (normalized,)
