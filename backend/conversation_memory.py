import os


RECENT_CONTEXT_MAX_TOKENS = int(os.getenv("RECENT_CONTEXT_MAX_TOKENS", "48000"))
MEMORY_UPDATE_INTERVAL_TOKENS = int(os.getenv("MEMORY_UPDATE_INTERVAL_TOKENS", "44000"))

if not 0 < MEMORY_UPDATE_INTERVAL_TOKENS < RECENT_CONTEXT_MAX_TOKENS:
    raise RuntimeError(
        "Token limits must satisfy 0 < memory interval < recent context maximum"
    )


def message_token_count(message):
    token_count = message["token_count"] if "token_count" in message.keys() else None
    return max(1, int(token_count) if token_count is not None else len(message["content"]))


def select_recent_messages(messages, covered_through_message_id):
    """Select a contiguous suffix while never omitting unsummarized messages."""
    if not messages:
        return []

    first_uncovered_index = len(messages)
    for index, message in enumerate(messages):
        if message["id"] > covered_through_message_id:
            first_uncovered_index = index
            break

    selected_start = len(messages)
    selected_tokens = 0
    for index in range(len(messages) - 1, -1, -1):
        token_count = message_token_count(messages[index])
        is_required = index >= first_uncovered_index
        if not is_required and selected_tokens + token_count > RECENT_CONTEXT_MAX_TOKENS:
            break
        selected_start = index
        selected_tokens += token_count

    return messages[selected_start:]


def stable_messages_for_memory(messages, covered_through_message_id):
    """Return new stable messages, excluding the latest editable/regenerable turn."""
    latest_user_message_id = next(
        (message["id"] for message in reversed(messages) if message["role"] == "user"),
        None,
    )
    if latest_user_message_id is None:
        return []
    return [
        message
        for message in messages
        if covered_through_message_id < message["id"] < latest_user_message_id
    ]


def should_update_memory(messages, covered_through_message_id):
    stable_messages = stable_messages_for_memory(messages, covered_through_message_id)
    return (
        sum(message_token_count(message) for message in stable_messages)
        >= MEMORY_UPDATE_INTERVAL_TOKENS
    )


def allocate_input_tokens(messages, instructions, input_tokens):
    """Allocate provider-reported input usage to messages by their text weight."""
    if not messages or not input_tokens:
        return {}
    instruction_weight = max(1, len(instructions))
    message_weights = [max(1, len(message["content"])) for message in messages]
    total_weight = instruction_weight + sum(message_weights)
    return {
        message["id"]: max(1, round(input_tokens * weight / total_weight))
        for message, weight in zip(messages, message_weights)
        if message.get("id") is not None
    }