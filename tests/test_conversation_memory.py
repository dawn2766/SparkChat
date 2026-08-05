import unittest

from backend.conversation_memory import (
    allocate_input_tokens,
    select_recent_messages,
    should_update_memory,
    stable_messages_for_memory,
)


def message(message_id, role="user", content="x", token_count=1):
    return {"id": message_id, "role": role, "content": content, "token_count": token_count}


class ConversationMemoryTest(unittest.TestCase):
    def test_recent_context_contains_every_uncovered_message(self):
        messages = [message(index, token_count=12000) for index in range(1, 8)]
        selected = select_recent_messages(messages, covered_through_message_id=2)

        self.assertEqual([item["id"] for item in selected], [3, 4, 5, 6, 7])
        self.assertGreater(sum(item["token_count"] for item in selected), 48000)

    def test_recent_context_fills_as_close_to_maximum_as_contiguous_messages_allow(self):
        messages = [message(index, token_count=2000) for index in range(1, 31)]
        selected = select_recent_messages(messages, covered_through_message_id=30)
        selected_tokens = sum(item["token_count"] for item in selected)

        self.assertEqual([item["id"] for item in selected], list(range(7, 31)))
        self.assertEqual(selected_tokens, 48000)

    def test_recent_context_stops_before_the_next_message_would_exceed_maximum(self):
        messages = [message(1, token_count=5000), message(2, token_count=44000)]

        selected = select_recent_messages(messages, covered_through_message_id=2)

        self.assertEqual([item["id"] for item in selected], [2])

    def test_latest_user_turn_is_not_stable_memory(self):
        messages = [
            message(1, "user", token_count=22000),
            message(2, "assistant", token_count=22000),
            message(3, "user", token_count=22000),
            message(4, "assistant", token_count=22000),
        ]

        stable = stable_messages_for_memory(messages, covered_through_message_id=0)

        self.assertEqual([item["id"] for item in stable], [1, 2])
        self.assertTrue(should_update_memory(messages, covered_through_message_id=0))

    def test_input_usage_is_distributed_to_unmeasured_messages(self):
        messages = [message(1, content="a"), message(2, content="" * 0 + "bbbb")]

        counts = allocate_input_tokens(messages, "instructions", 100)

        self.assertEqual(set(counts), {1, 2})
        self.assertGreater(counts[2], counts[1])


if __name__ == "__main__":
    unittest.main()
