"""Interactive onboarding questionnaire for nanobot."""
import importlib
import json
from typing import Any

import questionary
from pydantic import BaseModel

from nanobot.config.loader import get_config_path, load_config
from nanobot.config.schema import Config


def _get_channel_info() -> dict[str, tuple[str, type[BaseModel]]]:
    """Get channel info (display name + config class) from channel modules."""
    from nanobot.channels.registry import discover_channel_names

    result = {}
    for name in discover_channel_names():
        try:
            mod = importlib.import_module(f"nanobot.channels.{name}")
            # Find Config class in the module
            config_cls = None
            display_name = name.capitalize()
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
                    # Check if it looks like a config class (has 'enabled' field)
                    if hasattr(attr, "model_fields") and "enabled" in attr.model_fields:
                        config_cls = attr
                        break
                    # Also check for channels that don't have 'enabled' but have config
                    if "Config" in attr_name:
                        config_cls = attr
                        break

            if config_cls:
                # Try to get display name from config
                if hasattr(config_cls, "__doc__") and config_cls.__doc__:
                    # Extract name from docstring
                    doc = config_cls.__doc__.strip()
                    if doc:
                        display_name = doc.split("\n")[0].strip()
                result[name] = (display_name, config_cls)
        except Exception:
            pass
    return result


# Channel info loaded dynamically
_CHANNEL_INFO: dict[str, tuple[str, type[BaseModel]]] | None = None


def _get_channel_names() -> dict[str, str]:
    """Get channel display names."""
    global _CHANNEL_INFO
    if _CHANNEL_INFO is None:
        _CHANNEL_INFO = _get_channel_info()
    return {name: info[0] for name, info in _CHANNEL_INFO.items()}


def _get_channel_config_class(channel: str) -> type[BaseModel] | None:
    """Get channel config class."""
    global _CHANNEL_INFO
    if _CHANNEL_INFO is None:
        _CHANNEL_INFO = _get_channel_info()
    return _CHANNEL_INFO.get(channel, (None, None))[1]


# Provider info cached
_PROVIDER_INFO: dict[str, tuple[str, bool, bool, str]] | None = None  # name -> (display_name, is_gateway, is_local, default_api_base)


def _get_provider_info() -> dict[str, tuple[str, bool, bool, str]]:
    """Get provider info from registry (cached)."""
    global _PROVIDER_INFO
    if _PROVIDER_INFO is None:
        from nanobot.providers.registry import PROVIDERS

        _PROVIDER_INFO = {}
        for spec in PROVIDERS:
            _PROVIDER_INFO[spec.name] = (
                spec.display_name or spec.name,
                spec.is_gateway,
                spec.is_local,
                spec.default_api_base,
            )
    return _PROVIDER_INFO


def _get_provider_names() -> dict[str, str]:
    """Get provider display names from schema."""
    info = _get_provider_info()
    return {name: data[0] for name, data in info.items()}

def _get_provider_fields(provider: str) -> list[tuple[str, str]]:
    """Get required fields for a provider."""
    fields = [("api_key", "API Key")]

    # Use cached provider info
    info = _get_provider_info()
    if provider in info:
        # Always show api_base for non-OAuth providers since users may need to customize it
        fields.append(("api_base", "API Base URL"))

    if provider == "custom":
        fields.append(("extra_headers", "Extra Headers (JSON, optional)"))

    return fields


def _configure_single_provider(config: Config, provider: str) -> None:
    """Configure a single provider."""
    provider_config = getattr(config.providers, provider)
    provider_name = _get_provider_names().get(provider, provider)

    # Check if provider config is a dict or object
    is_dict = isinstance(provider_config, dict)

    fields = _get_provider_fields(provider)

    # Show current config status first
    print(f"\n--- Configuring {provider_name} ---")
    for field_key, field_label in fields:
        if is_dict:
            existing_value = provider_config.get(field_key, None)
        else:
            existing_value = getattr(provider_config, field_key, None)
        if existing_value:
            if "key" in field_key.lower() or "secret" in field_key.lower():
                print(f"  {field_label}: [configured]")
            elif field_key == "api_base":
                print(f"  {field_label}: {existing_value}")
            elif isinstance(existing_value, dict):
                print(f"  {field_label}: {json.dumps(existing_value)}")
            else:
                print(f"  {field_label}: {existing_value}")
        else:
            print(f"  {field_label}: [not set]")
    print()

    for field_key, field_label in fields:
        # Check if there's an existing value
        if is_dict:
            existing_value = provider_config.get(field_key, None)
        else:
            existing_value = getattr(provider_config, field_key, None)
        has_existing = bool(existing_value)

        if field_key == "api_key":
            if has_existing:
                choice = questionary.select(
                    f"[{provider_name}] {field_label}",
                    choices=["Enter new value", "Keep existing value"],
                    default="Keep existing value",
                ).ask()
                if choice == "Keep existing value":
                    continue
                # else: enter new value

            value = questionary.password(
                f"[{provider_name}] {field_label} (enter new value):",
            ).ask()
            if value:
                if is_dict:
                    provider_config[field_key] = value
                else:
                    setattr(provider_config, field_key, value)
        elif field_key == "api_base":
            if has_existing:
                choice = questionary.select(
                    f"[{provider_name}] {field_label}",
                    choices=["Enter new value", "Keep existing value"],
                    default="Keep existing value",
                ).ask()
                if choice == "Keep existing value":
                    continue
                # else: enter new value
            default = existing_value or ""
            value = questionary.text(
                f"[{provider_name}] {field_label} (enter new value):",
                default=default,
            ).ask()
            if value:
                if is_dict:
                    provider_config[field_key] = value
                else:
                    setattr(provider_config, field_key, value)
        elif field_key == "extra_headers":
            if has_existing:
                choice = questionary.select(
                    f"[{provider_name}] {field_label}",
                    choices=["Enter new value", "Keep existing value"],
                    default="Keep existing value",
                ).ask()
                if choice == "Keep existing value":
                    continue
                # else: enter new value
            default = ""
            if existing_value:
                default = json.dumps(existing_value)
            value = questionary.text(
                f"[{provider_name}] {field_label} (enter new value):",
                default=default,
            ).ask()
            if value:
                try:
                    new_value = json.loads(value)
                    if is_dict:
                        provider_config[field_key] = new_value
                    else:
                        setattr(provider_config, field_key, new_value)
                except json.JSONDecodeError:
                    pass  # Ignore invalid JSON


def _to_camel_case(snake_str: str) -> str:
    """Convert snake_case to camelCase."""
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def _get_config_value(channel_config: Any, field_key: str, is_dict: bool) -> Any:
    """Get config value, trying both snake_case and camelCase."""
    if is_dict:
        # Try snake_case first, then camelCase
        value = channel_config.get(field_key, None)
        if value is None:
            value = channel_config.get(_to_camel_case(field_key), None)
        return value
    else:
        return getattr(channel_config, field_key, None)


def _set_config_value(channel_config: Any, field_key: str, value: Any, is_dict: bool) -> None:
    """Set config value, using the key that already exists."""
    if is_dict:
        # Check if camelCase version exists, use that; otherwise use snake_case
        camel_key = _to_camel_case(field_key)
        if camel_key in channel_config:
            channel_config[camel_key] = value
        else:
            channel_config[field_key] = value
    else:
        setattr(channel_config, field_key, value)


def _configure_single_channel(config: Config, channel: str) -> None:
    """Configure a single channel."""
    from pydantic import BaseModel

    channel_config: Any = getattr(config.channels, channel)
    channel_name = _get_channel_names().get(channel, channel)

    # Check if channel config is a dict or object
    is_dict = isinstance(channel_config, dict)

    # Get config class to extract field definitions
    config_cls = _get_channel_config_class(channel)

    # Get fields from config class model
    fields = []
    if config_cls and hasattr(config_cls, "model_fields"):
        for field_name, field_info in config_cls.model_fields.items():
            # Skip 'enabled' field - we handle it separately
            if field_name == "enabled":
                continue
            # Skip fields that are not string/bool/int (complex types)
            field_type = field_info.annotation
            if field_type is None:
                continue
            # Get field description from docstring
            description = field_name
            if field_info.description:
                description = field_info.description
            fields.append((field_name, description))

    # Build field choices with status
    def get_field_choices() -> list[str]:
        choices = []
        for field_key, field_label in fields:
            existing_value = _get_config_value(channel_config, field_key, is_dict)
            if existing_value:
                if "password" in field_key.lower() or "secret" in field_key.lower():
                    choices.append(f"{field_label} [configured]")
                elif isinstance(existing_value, list):
                    choices.append(f"{field_label}: {', '.join(str(v) for v in existing_value)}")
                else:
                    choices.append(f"{field_label}: {existing_value}")
            else:
                choices.append(f"{field_label} [not set]")
        return choices + ["Done"]

    while True:
        # Show current config status
        print(f"\n--- Configuring {channel_name} ---")
        for i, (field_key, field_label) in enumerate(fields):
            existing_value = _get_config_value(channel_config, field_key, is_dict)
            if existing_value:
                if "password" in field_key.lower() or "secret" in field_key.lower():
                    print(f"  {i + 1}. {field_label}: [configured]")
                elif isinstance(existing_value, list):
                    print(f"  {i + 1}. {field_label}: {', '.join(str(v) for v in existing_value)}")
                else:
                    print(f"  {i + 1}. {field_label}: {existing_value}")
            else:
                print(f"  {i + 1}. {field_label}: [not set]")
        print()

        try:
            choices = get_field_choices()
            answer = questionary.select(
                "Select field to configure (arrow keys + enter):",
                choices=choices,
                qmark=">",
            ).ask()

            if answer == "Done" or answer is None:
                break

            # Extract field index from choice (e.g., "1. imapHost: xxx" -> 0)
            field_idx = 0
            for i, c in enumerate(choices):
                if c == answer:
                    field_idx = i
                    break
            if field_idx >= len(fields):
                break

            field_key, field_label = fields[field_idx]
            existing_value = _get_config_value(channel_config, field_key, is_dict)
            has_existing = bool(existing_value) if not isinstance(existing_value, list) else bool(existing_value)

            # Determine field type
            is_password = "password" in field_key.lower() or "secret" in field_key.lower()
            is_list = False
            if config_cls and hasattr(config_cls, "model_fields"):
                field_type = config_cls.model_fields.get(field_key)
                if field_type:
                    type_str = str(field_type.annotation)
                    is_list = "list" in type_str.lower()

            if is_password:
                if has_existing:
                    choice = questionary.select(
                        f"[{channel_name}] {field_label}",
                        choices=["Enter new value", "Keep existing value"],
                        default="Keep existing value",
                    ).ask()
                    if choice == "Keep existing value":
                        continue
                    # else: enter new value

                value = questionary.password(
                    f"[{channel_name}] {field_label} (enter new value):",
                ).ask()
                new_value = value if value else None
            else:
                default = existing_value if existing_value else ""
                if is_list and isinstance(default, list):
                    default = ",".join(str(v) for v in default)
                value = questionary.text(
                    f"[{channel_name}] {field_label}",
                    default=str(default),
                ).ask()
                if value:
                    if is_list:
                        new_value = [v.strip() for v in value.split(",") if v.strip()]
                    else:
                        new_value = value
                else:
                    new_value = None

            if new_value:
                _set_config_value(channel_config, field_key, new_value, is_dict)

        except KeyboardInterrupt:
            print("\nReturning to channel selection...")
            break

    # Enable the channel
    if is_dict:
        channel_config["enabled"] = True
    else:
        channel_config.enabled = True


def _configure_providers(config: Config) -> None:
    """Configure LLM providers."""
    choices = list(_get_provider_names().keys()) + ["Done"]
    while True:
        try:
            answer = questionary.select(
                "Select LLM Provider to configure (arrow keys + enter):",
                choices=choices,
                qmark=">",
            ).ask()

            if answer is None or answer == "Done":
                break

            _configure_single_provider(config, answer)
        except KeyboardInterrupt:
            print("\nReturning to main menu...")
            break


def _configure_channels(config: Config) -> None:
    """Configure chat channels."""
    channel_names = _get_channel_names()
    choices = list(channel_names.keys()) + ["Done"]
    while True:
        try:
            answer = questionary.select(
                "Select Channel to configure (arrow keys + enter):",
                choices=choices,
                qmark=">",
            ).ask()

            if answer is None or answer == "Done":
                break

            _configure_single_channel(config, answer)
        except KeyboardInterrupt:
            print("\nReturning to main menu...")
            break


def _show_summary(config: Config) -> str:
    """Generate configuration summary."""
    lines = ["=" * 40, "Configuration Summary", "=" * 40, ""]

    # Providers
    lines.append("[LLM Providers]")
    for name, display in _get_provider_names().items():
        provider = getattr(config.providers, name)
        # Handle both object and dict
        api_key = provider.api_key if hasattr(provider, "api_key") else provider.get("api_key", "")
        if api_key:
            lines.append(f"  + {display}: configured")
        else:
            lines.append(f"  o {display}: not configured")

    lines.append("")

    # Channels
    lines.append("[Chat Channels]")
    channel_names = _get_channel_names()
    for name, display in channel_names.items():
        channel = getattr(config.channels, name)
        # Handle both object and dict
        if hasattr(channel, "enabled"):
            enabled = channel.enabled
        else:
            enabled = channel.get("enabled", False) if isinstance(channel, dict) else False

        if enabled:
            lines.append(f"  + {display}: enabled")
        else:
            lines.append(f"  o {display}: disabled")

    lines.append("=" * 40)
    return "\n".join(lines)


def run_onboard() -> Config:
    """Run the interactive onboarding questionnaire."""
    config_path = get_config_path()

    # Load existing config or create new one
    if config_path.exists():
        config = load_config()
    else:
        config = Config()

    # Main menu loop
    while True:
        try:
            answer = questionary.select(
                "Welcome to nanobot Setup Wizard",
                choices=[
                    "Configure LLM Provider",
                    "Configure Chat Channel",
                    "View Configuration Summary",
                    "Save and Exit",
                ],
                qmark=">",
            ).ask()

            if answer == "Configure LLM Provider":
                _configure_providers(config)
            elif answer == "Configure Chat Channel":
                _configure_channels(config)
            elif answer == "View Configuration Summary":
                summary = _show_summary(config)
                print(summary)
            elif answer == "Save and Exit":
                break
        except KeyboardInterrupt:
            print("\n\nOperation cancelled. Your changes have been saved.")
            break

    return config
