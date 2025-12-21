# --- browser_utils/initialization/network.py ---
import asyncio
import json
import logging

from playwright.async_api import BrowserContext as AsyncBrowserContext

from .scripts import add_init_scripts_to_context

logger = logging.getLogger("AIStudioProxyServer")


async def setup_network_interception_and_scripts(context: AsyncBrowserContext):
    """Setup network interception and script injection"""
    try:
        from config.settings import ENABLE_SCRIPT_INJECTION

        if not ENABLE_SCRIPT_INJECTION:
            logger.debug("[Network] Script injection disabled")
            return

        # Setup network interception
        await _setup_model_list_interception(context)

        # Optional: still inject scripts as fallback
        await add_init_scripts_to_context(context)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Error setting up network interception and scripts: {e}")


async def _setup_model_list_interception(context: AsyncBrowserContext):
    """Setup model list network interception"""
    try:

        async def handle_model_list_route(route):
            """Handle model list request route"""
            request = route.request

            # Check if it's a model list request
            if "alkalimakersuite" in request.url and "ListModels" in request.url:
                logger.info(f"Intercepted model list request: {request.url}")

                # Continue original request
                response = await route.fetch()

                # Get original response body
                original_body = await response.body()

                # Modify response
                modified_body = await _modify_model_list_response(
                    original_body, request.url
                )

                # Return modified response
                await route.fulfill(response=response, body=modified_body)
            else:
                # For other requests, continue normally
                await route.continue_()

        # Register route interceptor
        await context.route("**/*", handle_model_list_route)
        logger.info("Model list network interception setup")

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Error setting up model list network interception: {e}")


async def _modify_model_list_response(original_body: bytes, url: str) -> bytes:
    """Modify model list response"""
    try:
        # Decode response body
        original_text = original_body.decode("utf-8")

        # Handle anti-hijack prefix
        ANTI_HIJACK_PREFIX = ")]}'\n"
        has_prefix = False
        if original_text.startswith(ANTI_HIJACK_PREFIX):
            original_text = original_text[len(ANTI_HIJACK_PREFIX) :]
            has_prefix = True

        # Parse JSON
        try:
            json_data = json.loads(original_text)
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to parse model list response JSON: {json_err}")
            return original_body

        # Inject models
        modified_data = await _inject_models_to_response(json_data, url)

        # Serialize back to JSON
        modified_text = json.dumps(modified_data, separators=(",", ":"))

        # Add prefix back
        if has_prefix:
            modified_text = ANTI_HIJACK_PREFIX + modified_text

        logger.info("Successfully modified model list response")
        return modified_text.encode("utf-8")

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Error modifying model list response: {e}")
        return original_body


async def _inject_models_to_response(json_data: dict, url: str) -> dict:
    """Inject models into the response"""
    try:
        from browser_utils.operations import _get_injected_models

        # Get models to inject
        injected_models = _get_injected_models()
        if not injected_models:
            logger.info("No models to inject")
            return json_data

        # Find models array
        models_array = _find_model_list_array(json_data)
        if not models_array:
            logger.warning("Models array structure not found")
            return json_data

        # Find template model
        template_model = _find_template_model(models_array)
        if not template_model:
            logger.warning("Template model not found")
            return json_data

        # Inject models
        for model in reversed(injected_models):  # Reverse to maintain order
            model_name = model["raw_model_path"]

            # Check if model already exists
            if not any(
                m[0] == model_name
                for m in models_array
                if isinstance(m, list) and len(m) > 0
            ):
                # Create new model entry
                new_model = json.loads(json.dumps(template_model))  # Deep copy
                new_model[0] = model_name  # name
                new_model[3] = model["display_name"]  # display name
                new_model[4] = model["description"]  # description

                # Add special flag indicating network-injected model
                # Append special field at the end of the model array
                if len(new_model) > 10:  # Ensure enough space
                    new_model.append("__NETWORK_INJECTED__")
                else:
                    # Extend to sufficient length if needed
                    while len(new_model) <= 10:
                        new_model.append(None)
                    new_model.append("__NETWORK_INJECTED__")

                # Insert at the beginning
                models_array.insert(0, new_model)
                logger.info(
                    f"Network intercepted injected model: {model['display_name']}"
                )

        return json_data

    except Exception as e:
        logger.error(f"Error injecting models into response: {e}")
        return json_data


def _find_model_list_array(obj):
    """Recursively find model list array"""
    if not obj:
        return None

    # Check if it's a models array
    if isinstance(obj, list) and len(obj) > 0:
        if all(
            isinstance(item, list)
            and len(item) > 0
            and isinstance(item[0], str)
            and item[0].startswith("models/")
            for item in obj
        ):
            return obj

    # Recursive search
    if isinstance(obj, dict):
        for value in obj.values():
            result = _find_model_list_array(value)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_model_list_array(item)
            if result:
                return result

    return None


def _find_template_model(models_array):
    """Find template model, preferring flash, then pro, then any valid model"""
    if not models_array:
        return None

    # Priority 1: look for flash model
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            model_name = model[0] if len(model) > 0 else ""
            if "flash" in model_name.lower():
                return model

    # Priority 2: look for pro model
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            model_name = model[0] if len(model) > 0 else ""
            if "pro" in model_name.lower():
                return model

    # Finally: return first valid model
    for model in models_array:
        if isinstance(model, list) and len(model) > 7:
            return model

    return None
