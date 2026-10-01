"""Validate approved text templates and construct provider parameters server-side."""

import re
from typing import Any


def template_fields(template: dict[str, Any]) -> list[dict[str, str]]:
    fields = []
    for component in template.get("components", []):
        kind = component.get("type", "").lower()
        if kind == "footer":
            continue
        if kind not in {"header", "body"} or component.get("format", "TEXT") != "TEXT":
            raise ValueError(
                "This composer supports text header/body templates; media and button templates require a different composer"
            )
        for name in dict.fromkeys(re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", component.get("text", ""))):
            fields.append({"component": kind, "name": name})
    return fields


def build_template(template: dict[str, Any], parameters: list[str]) -> tuple[dict[str, Any], str]:
    fields = template_fields(template)
    if len(fields) != len(parameters):
        raise ValueError(f"This template requires {len(fields)} parameters")
    components: dict[str, list[dict[str, str]]] = {}
    display = {item["type"].lower(): item.get("text", "") for item in template.get("components", [])}
    for field, value in zip(fields, parameters, strict=True):
        parameter = {"type": "text", "text": value}
        if not field["name"].isdigit():
            parameter["parameter_name"] = field["name"]
        components.setdefault(field["component"], []).append(parameter)
        display[field["component"]] = display[field["component"]].replace("{{" + field["name"] + "}}", value)
    return {
        "name": template["name"],
        "language": {"code": template["language"]},
        "components": [{"type": kind, "parameters": values} for kind, values in components.items()],
    }, "\n".join(display.values())
