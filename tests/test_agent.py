from aurora.agent import ToolSpec, run_agent


class FakeLLM:
    """Returns scripted assistant messages in order."""

    def __init__(self, scripted):
        self._scripted = list(scripted)

    def chat(self, messages, tools=None):
        return self._scripted.pop(0)


def _tool_call(name, args="{}", call_id="c1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": args}}],
    }


def test_plain_text_no_tools():
    llm = FakeLLM([{"role": "assistant", "content": "hello"}])
    result = run_agent(llm, [{"role": "user", "content": "hi"}], [])
    assert result.text == "hello"
    assert not result.is_action


def test_read_tool_then_answer():
    calls = []
    tool = ToolSpec(
        name="list_unread",
        schema={"type": "function", "function": {"name": "list_unread", "parameters": {}}},
        handler=lambda args: calls.append(args) or '[{"from": "Bob"}]',
    )
    llm = FakeLLM([_tool_call("list_unread"), {"role": "assistant", "content": "1 from Bob."}])
    messages = [{"role": "user", "content": "any mail?"}]
    result = run_agent(llm, messages, [tool])
    assert result.text == "1 from Bob."
    assert calls == [{}]  # the tool ran
    # The tool result was threaded back into the conversation.
    assert any(m.get("role") == "tool" for m in messages)


def test_action_tool_short_circuits():
    tool = ToolSpec(
        name="send_reply",
        schema={"type": "function", "function": {"name": "send_reply", "parameters": {}}},
        is_action=True,
    )
    llm = FakeLLM([_tool_call("send_reply", args='{"body": "hi"}')])
    result = run_agent(llm, [{"role": "user", "content": "reply"}], [tool])
    assert result.is_action
    assert result.action_name == "send_reply"
    assert result.action_args == {"body": "hi"}


def test_tool_error_is_captured_and_loop_continues():
    def boom(args):
        raise ValueError("nope")

    tool = ToolSpec(
        name="list_unread",
        schema={"type": "function", "function": {"name": "list_unread", "parameters": {}}},
        handler=boom,
    )
    llm = FakeLLM([_tool_call("list_unread"), {"role": "assistant", "content": "recovered"}])
    messages = [{"role": "user", "content": "mail?"}]
    result = run_agent(llm, messages, [tool])
    assert result.text == "recovered"
    tool_msg = next(m for m in messages if m.get("role") == "tool")
    assert "error" in tool_msg["content"].lower()


def test_max_steps_forces_final_answer():
    # LLM keeps asking for the tool; after the step budget, a final no-tools call
    # yields a natural-language answer instead of dead-ending.
    tool = ToolSpec(
        name="list_unread",
        schema={"type": "function", "function": {"name": "list_unread", "parameters": {}}},
        handler=lambda args: "[]",
    )
    scripted = [_tool_call("list_unread") for _ in range(3)]
    scripted.append({"role": "assistant", "content": "I checked but found nothing new."})
    result = run_agent(FakeLLM(scripted), [{"role": "user", "content": "mail?"}], [tool], max_steps=3)
    assert result.text == "I checked but found nothing new."
    assert not result.is_action
