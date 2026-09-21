"""Frame untrusted structured evidence inside explicit data boundaries.

Owns: JSON escaping and context delimiters.
Does not own: Prompt instructions or semantic injection resistance claims.
"""

from pydantic import BaseModel


def data_block(label: str, value: BaseModel, *, exclude_unset: bool = False) -> str:
    """Encode angle brackets so data cannot syntactically close its wrapper.

    Args:
        label: Host-controlled block name.
        value: Validated evidence containing potentially hostile strings.
    Returns:
        Delimited JSON with data angle brackets escaped.
    """
    encoded = (
        value.model_dump_json(exclude_unset=exclude_unset)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return f"<{label}>\n{encoded}\n</{label}>"
