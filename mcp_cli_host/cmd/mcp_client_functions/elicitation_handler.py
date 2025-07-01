from mcp.shared.context import RequestContext
from mcp import ClientSession, types
from typing import Any
from rich.console import Console
from mcp_cli_host.cmd.utils import CLEAR_RIGHT, PREV_LINE
import logging
from typing import Dict, Union, Tuple
import re

console = Console()
log = logging.getLogger("mcp_cli_host")


def check_flat_schema(schema: Dict[str, Any]) -> list[tuple[str, bool, any]]:
    """
    parse flat JSON Schema, return tuple for name, input requirement, and isrequired.
    input should only include primitive properties(string/number/boolean/null)
    """
    propertie_names: list[tuple[str, bool, any]] = []

    properties = schema.get("properties", {})
    required_fields = schema.get("required", [])
    
    for prop_name, prop_config in properties.items():
        prop_type = prop_config.get("type", "unknown")
        is_required = prop_name in required_fields
        
        if prop_type != "string" and prop_type != "number" and prop_type != "integer" and prop_type != "boolean" and prop_type != "null":
            log.warning(f"Unsupported type {prop_type} for property {prop_name}, skipping.")
            raise ValueError(f"Unsupported type {prop_type} for property {prop_name}")

        propertie_names.append((prop_name, is_required, prop_config))

    return propertie_names

def build_description(prop_config: Dict[str, Any]) -> str:
    """
    Build a comprehensive description for the property based on its configuration.
    Includes constraints, format requirements, and enum options with display names.
    """
    description = prop_config.get("description", "")
    
    # String constraints
    if prop_config.get("type") == "string":
        if "minLength" in prop_config:
            description += f" Minimum length: {prop_config['minLength']} characters."
        if "maxLength" in prop_config:
            description += f" Maximum length: {prop_config['maxLength']} characters."
        if "format" in prop_config:
            format_desc = {
                "email": "Must be a valid email address",
                "uri": "Must be a valid URL",
                "date": "Must be in YYYY-MM-DD format",
                "date-time": "Must be in ISO 8601 format (e.g., 2023-12-31T23:59:59Z)"
            }.get(prop_config["format"], f"Must be in {prop_config['format']} format")
            description += f" {format_desc}."
    
    # Number constraints
    elif prop_config.get("type") in ("number", "integer"):
        if "minimum" in prop_config:
            description += f" Minimum value: {prop_config['minimum']}."
        if "maximum" in prop_config:
            description += f" Maximum value: {prop_config['maximum']}."
    
    # Enum values
    if "enum" in prop_config:
        options = prop_config.get("enumNames", prop_config["enum"])
        description += " Valid options: " + ", ".join(f"'{x}'" for x in options) + "."
    
    return description.strip()


def _validate_type(value: Any, config: Dict[str, Any]) -> Tuple[bool, str, any]:
    expected_type = config.get("type")
    typed_value: any = value
    try:
        if expected_type == "integer":
            typed_value = int(value)
        elif expected_type == "number":
            typed_value = float(value)
        elif expected_type == "boolean":
            if value.lower() in ('yes', 'true', 't', 'y', '1'):
                typed_value = True
            elif value.lower() in ('no', 'false', 'f', 'n', '0'):
                typed_value = False
            else:
                raise ValueError()
        elif expected_type == "string" and "enum" in config:
            if value not in config["enumNames"]:
                raise ValueError(f"Please select from: {', '.join(config['enumNames'])}")
            index = config["enumNames"].index(value)
            typed_value = config["enum"][index]
    except ValueError as e:
        return False, e.args[0] if len(e.args) > 0 else f"Please enter a valid {expected_type} value", None

    return True, "", typed_value

def _validate_string(value: str, config: Dict[str, Any]) -> Tuple[bool, str]:
    if "minLength" in config and len(value) < config["minLength"]:
        return False, f"Minimum length: {config['minLength']} characters required"
    
    if "maxLength" in config and len(value) > config["maxLength"]:
        return False, f"Maximum length: {config['maxLength']} characters required"
    
    if "format" in config:
        format_validators = {
            "email": lambda x: "@" in x and "." in x.partition("@")[2],
            "uri": lambda x: x.startswith(("http://", "https://")),
            "date": lambda x: re.fullmatch(r"\d{4}-\d{2}-\d{2}", x),
            "date-time": lambda x: re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?", x)
        }
        if config["format"] in format_validators:
            if not format_validators[config["format"]](value):
                return False, f"Please enter a valid {config['format']}"
    
        if "enum" in config:
            if value not in config["enumNames"]:
                options = config.get("enumNames")
                return False, f"Please select from: {', '.join(options)}"
            
    return True, ""

def _validate_number(value: Union[int, float], config: Dict[str, Any]) -> Tuple[bool, str]:
    if "minimum" in config and value < config["minimum"]:
        return False, f"Please enter a value no less than {config['minimum']}"
    
    if "maximum" in config and value > config["maximum"]:
        return False, f"Please enter a value no greater than {config['maximum']}"
    
    return True, ""

def validate_input(value: Any, prop_config: Dict[str, Any]) -> Tuple[bool, str, any]:
    type_ok, type_msg, typed_value = _validate_type(value, prop_config)
    if not type_ok:
        return False, type_msg, None

    valid, msg = True, ""
    if prop_config.get("type") == "string":
        valid, msg = _validate_string(typed_value, prop_config)
    elif prop_config.get("type") in ("number", "integer"):
        valid, msg = _validate_number(typed_value, prop_config)
    
    return valid, msg, typed_value if valid else None

class ElicitationCallback:
    def __init__(self):
        pass

    async def __call__(
        self,
        context: RequestContext["ClientSession", Any],
        request: types.ElicitRequestParams,
    ) -> types.ElicitResult | types.ErrorData:
        properties: list[tuple[str, bool, any]] = check_flat_schema(request.requestedSchema)
        properties_des = [prop[2]["title"] if prop[2].get("title", None) else prop[0] + "(required)" if prop[1] else prop[2]["title"] if prop[2].get("title", None) else prop[0] for prop in properties]
        property_inputs: Dict[str, Any] = {}
        try:
            while True:
                try:
                    prompt = (
                        f"[bold magenta]Received extra information request from Server, do you want to send "
                        f"these information to server (Type 'yes' to continue, 'no' to reject, 'cancel' to cancel):[/bold magenta]\n"
                        f"[green]{request.message}\n"
                        f"{', '.join(properties_des)}[/green]\n"
                        "Please be mindful of privacy protection. (yes/no/cancel): "
                    )
                    user_confirmation = console.input(prompt)
                    print(f"{PREV_LINE}{CLEAR_RIGHT}")

                    if not user_confirmation:
                        continue

                    if user_confirmation != "yes" and user_confirmation != "no" and user_confirmation != "cancel":
                        continue

                    console.print(
                        f" 🤠 [bold bright_yellow]You[/bold bright_yellow]: [bold bright_white]{user_confirmation}[/bold bright_white]")

                    if user_confirmation == "yes":
                        for prop in properties:
                            while True:
                                prop_name, is_required, prop_config = prop
                                description = build_description(prop_config)
                                prop_title = prop_config["title"] if prop_config.get("title", None) else prop_name
                                if is_required:
                                    value = console.input(
                                        f"[bold magenta]Please input [green]{prop_title}[/green] [red](required)[/red] {description}:[/bold magenta]\n")
                                else:
                                    value = console.input(
                                        f"[bold magenta]Please input [green]{prop_title}[/green] [yellow](optional)[/yellow] {description}:[/bold magenta]\n")
                                if not value and is_required:
                                    console.print(
                                        f"[red]Error: {prop_title} is required but you provided nothing.[/red]")
                                    continue
                                
                                if value:
                                    success, error_ms, typed_value = validate_input(value, prop_config)
                                    if not success:
                                        console.print(
                                            f"[red]Error: {error_ms}[/red]")
                                        continue
                                    # If the value is valid, we can proceed
                                    property_inputs[prop_name] = typed_value
                                break
                        
                        return types.ElicitResult(
                            action="accept",
                            content=property_inputs
                        )
                    elif user_confirmation == "no":
                        console.print(" ❌ reject the request ")
                        return types.ElicitResult(
                            action="decline",
                        )
                    elif user_confirmation == "cancel":
                        console.print(" ⭕️ cancel the request ")
                        return types.ElicitResult(
                            action="cancel",
                        )

                except KeyboardInterrupt:
                    console.print(" ❌ User cancelled the request ")
                    return types.ElicitResult(
                        action="cancel",
                    )

                except Exception:
                    raise
        except Exception:
            raise

