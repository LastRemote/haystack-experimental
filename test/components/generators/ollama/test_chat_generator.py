from unittest.mock import Mock, patch
import sys
import json
import pytest

from haystack.components.generators.utils import print_streaming_chunk
from haystack.dataclasses import StreamingChunk
from ollama._types import ResponseError

from haystack_experimental.dataclasses import (
    ChatMessage,
    ChatRole,
    TextContent,
    ToolCall,
    Tool,
)
from haystack_experimental.components.generators.ollama.chat.chat_generator import (
    OllamaChatGenerator,
    _convert_message_to_ollama_format,
)


@pytest.fixture
def tools():
    tool_parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }
    tool = Tool(
        name="weather",
        description="useful to determine the weather in a given location",
        parameters=tool_parameters,
        function=lambda x: x,
    )

    return [tool]


def test_convert_message_to_ollama_format():
    message = ChatMessage.from_system("You are good assistant")
    assert _convert_message_to_ollama_format(message) == {
        "role": "system",
        "content": "You are good assistant",
    }

    message = ChatMessage.from_user("I have a question")
    assert _convert_message_to_ollama_format(message) == {
        "role": "user",
        "content": "I have a question",
    }

    message = ChatMessage.from_assistant(text="I have an answer", meta={"finish_reason": "stop"})
    assert _convert_message_to_ollama_format(message) == {
        "role": "assistant",
        "content": "I have an answer",
    }

    message = ChatMessage.from_assistant(
        tool_calls=[ToolCall(id="123", tool_name="weather", arguments={"city": "Paris"})]
    )
    assert _convert_message_to_ollama_format(message) == {
        "role": "assistant",
        "tool_calls": [
            {
                "type": "function",
                "function": {"name": "weather", "arguments": {"city": "Paris"}},
            }
        ],
    }

    tool_result = json.dumps({"weather": "sunny", "temperature": "25"})
    message = ChatMessage.from_tool(
        tool_result=tool_result,
        origin=ToolCall(tool_name="weather", arguments={"city": "Paris"}),
    )
    assert _convert_message_to_ollama_format(message) == {
        "role": "tool",
        "content": tool_result,
    }


def test_convert_message_to_ollama_invalid():
    message = ChatMessage(_role=ChatRole.ASSISTANT, _content=[])
    with pytest.raises(ValueError):
        _convert_message_to_ollama_format(message)

    message = ChatMessage(
        _role=ChatRole.ASSISTANT,
        _content=[
            TextContent(text="I have an answer"),
            TextContent(text="I have another answer"),
        ],
    )
    with pytest.raises(ValueError):
        _convert_message_to_ollama_format(message)


class TestOllamaChatGenerator:
    def test_init_default(self):
        component = OllamaChatGenerator()
        assert component.model == "orca-mini"
        assert component.url == "http://localhost:11434"
        assert component.generation_kwargs == {}
        assert component.timeout == 120
        assert component.streaming_callback is None
        assert component.tools is None

    def test_init(self, tools):
        component = OllamaChatGenerator(
            model="llama2",
            url="http://my-custom-endpoint:11434",
            generation_kwargs={"temperature": 0.5},
            timeout=5,
            streaming_callback=print_streaming_chunk,
            tools=tools,
        )

        assert component.model == "llama2"
        assert component.url == "http://my-custom-endpoint:11434"
        assert component.generation_kwargs == {"temperature": 0.5}
        assert component.timeout == 5
        assert component.streaming_callback is print_streaming_chunk
        assert component.tools == tools

    def test_init_fail_with_duplicate_tool_names(self, tools):

        duplicate_tools = [tools[0], tools[0]]
        with pytest.raises(ValueError):
            OllamaChatGenerator(tools=duplicate_tools)

    def test_to_dict(self):
        tool = Tool(
            name="name",
            description="description",
            parameters={"x": {"type": "string"}},
            function=print,
        )

        component = OllamaChatGenerator(
            model="llama2",
            streaming_callback=print_streaming_chunk,
            url="custom_url",
            generation_kwargs={"max_tokens": 10, "some_test_param": "test-params"},
            tools=[tool],
        )
        data = component.to_dict()
        assert data == {
            "type": "haystack_experimental.components.generators.ollama.chat.chat_generator.OllamaChatGenerator",
            "init_parameters": {
                "timeout": 120,
                "model": "llama2",
                "url": "custom_url",
                "streaming_callback": "haystack.components.generators.utils.print_streaming_chunk",
                "generation_kwargs": {
                    "max_tokens": 10,
                    "some_test_param": "test-params",
                },
                "tools": [
                    {
                        "description": "description",
                        "function": "builtins.print",
                        "name": "name",
                        "parameters": {
                            "x": {
                                "type": "string",
                            },
                        },
                    },
                ],
            },
        }

    def test_from_dict(self):
        tool = Tool(
            name="name",
            description="description",
            parameters={"x": {"type": "string"}},
            function=print,
        )

        data = {
            "type": "haystack_experimental.components.generators.ollama.chat.chat_generator.OllamaChatGenerator",
            "init_parameters": {
                "timeout": 120,
                "model": "llama2",
                "url": "custom_url",
                "streaming_callback": "haystack.components.generators.utils.print_streaming_chunk",
                "generation_kwargs": {
                    "max_tokens": 10,
                    "some_test_param": "test-params",
                },
                "tools": [
                    {
                        "description": "description",
                        "function": "builtins.print",
                        "name": "name",
                        "parameters": {
                            "x": {
                                "type": "string",
                            },
                        },
                    },
                ],
            },
        }
        component = OllamaChatGenerator.from_dict(data)
        assert component.model == "llama2"
        assert component.streaming_callback is print_streaming_chunk
        assert component.url == "custom_url"
        assert component.generation_kwargs == {
            "max_tokens": 10,
            "some_test_param": "test-params",
        }
        assert component.timeout == 120
        assert component.tools == [tool]

    def test_build_message_from_ollama_response(self):
        model = "some_model"

        ollama_response = {
            "model": model,
            "created_at": "2023-12-12T14:13:43.416799Z",
            "message": {"role": "assistant", "content": "Hello! How are you today?"},
            "done": True,
            "total_duration": 5191566416,
            "load_duration": 2154458,
            "prompt_eval_count": 26,
            "prompt_eval_duration": 383809000,
            "eval_count": 298,
            "eval_duration": 4799921000,
        }

        observed = OllamaChatGenerator(model=model)._build_message_from_ollama_response(ollama_response)

        assert observed.role == "assistant"
        assert observed.text == "Hello! How are you today?"

    def test_build_message_from_ollama_response_with_tools(self):
        model = "some_model"

        ollama_response = {
            "model": model,
            "created_at": "2023-12-12T14:13:43.416799Z",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_current_weather",
                            "arguments": {"format": "celsius", "location": "Paris, FR"},
                        }
                    }
                ],
            },
            "done": True,
            "total_duration": 5191566416,
            "load_duration": 2154458,
            "prompt_eval_count": 26,
            "prompt_eval_duration": 383809000,
            "eval_count": 298,
            "eval_duration": 4799921000,
        }

        observed = OllamaChatGenerator(model=model)._build_message_from_ollama_response(ollama_response)

        assert observed.role == "assistant"
        assert observed.text == ""
        assert observed.tool_call == ToolCall(
            tool_name="get_current_weather",
            arguments={"format": "celsius", "location": "Paris, FR"},
        )

    @patch("haystack_integrations.components.generators.ollama.chat.chat_generator.Client")
    def test_run(self, mock_client):
        generator = OllamaChatGenerator()

        mock_response = {
            "model": "llama3.2",
            "created_at": "2023-12-12T14:13:43.416799Z",
            "message": {
                "role": "assistant",
                "content": "Fine. How can I help you today?",
            },
            "done": True,
            "total_duration": 5191566416,
            "load_duration": 2154458,
            "prompt_eval_count": 26,
            "prompt_eval_duration": 383809000,
            "eval_count": 298,
            "eval_duration": 4799921000,
        }

        mock_client_instance = mock_client.return_value
        mock_client_instance.chat.return_value = mock_response

        result = generator.run(messages=[ChatMessage.from_user("Hello! How are you today?")])

        mock_client_instance.chat.assert_called_once_with(
            model="orca-mini",
            messages=[{"role": "user", "content": "Hello! How are you today?"}],
            stream=False,
            tools=None,
            options={},
        )

        assert "replies" in result
        assert len(result["replies"]) == 1
        assert result["replies"][0].text == "Fine. How can I help you today?"
        assert result["replies"][0].role == "assistant"

    @patch("haystack_integrations.components.generators.ollama.chat.chat_generator.Client")
    def test_run_streaming(self, mock_client):
        streaming_callback_called = False

        def streaming_callback(chunk: StreamingChunk) -> None:
            nonlocal streaming_callback_called
            streaming_callback_called = True

        generator = OllamaChatGenerator(streaming_callback=streaming_callback)

        mock_response = iter(
            [
                {
                    "model": "llama3.2",
                    "created_at": "2023-12-12T14:13:43.416799Z",
                    "message": {"role": "assistant", "content": "first chunk "},
                    "done": False,
                },
                {
                    "model": "llama3.2",
                    "created_at": "2023-12-12T14:13:43.416799Z",
                    "message": {"role": "assistant", "content": "second chunk"},
                    "done": True,
                    "total_duration": 4883583458,
                    "load_duration": 1334875,
                    "prompt_eval_count": 26,
                    "prompt_eval_duration": 342546000,
                    "eval_count": 282,
                    "eval_duration": 4535599000,
                },
            ]
        )

        mock_client_instance = mock_client.return_value
        mock_client_instance.chat.return_value = mock_response

        result = generator.run(messages=[ChatMessage.from_user("irrelevant")])

        assert streaming_callback_called

        assert "replies" in result
        assert len(result["replies"]) == 1
        assert result["replies"][0].text == "first chunk second chunk"
        assert result["replies"][0].role == "assistant"

    def test_run_fail_with_tools_and_streaming(self, tools):
        component = OllamaChatGenerator(tools=tools, streaming_callback=print_streaming_chunk)

        with pytest.raises(ValueError):
            message = ChatMessage.from_user("irrelevant")
            component.run([message])

    @pytest.mark.integration
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="For simplicity, we only run the integration tests on Linux.",
    )
    def test_live_run(self):
        chat_generator = OllamaChatGenerator(model="llama3.2:3b")

        user_questions_and_assistant_answers = [
            ("What's the capital of France?", "Paris"),
            ("What is the capital of Canada?", "Ottawa"),
            ("What is the capital of Ghana?", "Accra"),
        ]

        for question, answer in user_questions_and_assistant_answers:
            message = ChatMessage.from_user(question)

            response = chat_generator.run([message])

            assert isinstance(response, dict)
            assert isinstance(response["replies"], list)
            assert answer in response["replies"][0].text

    @pytest.mark.integration
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="For simplicity, we only run the integration tests on Linux.",
    )
    def test_run_with_chat_history(self):
        chat_generator = OllamaChatGenerator(model="llama3.2:3b")

        chat_messages = [
            ChatMessage.from_user("What is the largest city in the United Kingdom by population?"),
            ChatMessage.from_assistant("London is the largest city in the United Kingdom by population"),
            ChatMessage.from_user("And what is the second largest?"),
        ]

        response = chat_generator.run(chat_messages)

        assert isinstance(response, dict)
        assert isinstance(response["replies"], list)

        assert any(city in response["replies"][-1].text for city in ["Manchester", "Birmingham", "Glasgow"])

    @pytest.mark.integration
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="For simplicity, we only run the integration tests on Linux.",
    )
    def test_run_model_unavailable(self):
        component = OllamaChatGenerator(model="unknown_model")

        with pytest.raises(ResponseError):
            message = ChatMessage.from_user("irrelevant")
            component.run([message])

    @pytest.mark.integration
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="For simplicity, we only run the integration tests on Linux.",
    )
    def test_run_with_streaming(self):
        streaming_callback = Mock()
        chat_generator = OllamaChatGenerator(model="llama3.2:3b", streaming_callback=streaming_callback)

        chat_messages = [
            ChatMessage.from_user("What is the largest city in the United Kingdom by population?"),
            ChatMessage.from_assistant("London is the largest city in the United Kingdom by population"),
            ChatMessage.from_user("And what is the second largest?"),
        ]

        response = chat_generator.run(chat_messages)

        streaming_callback.assert_called()

        assert isinstance(response, dict)
        assert isinstance(response["replies"], list)
        assert any(city in response["replies"][-1].text for city in ["Manchester", "Birmingham", "Glasgow"])

    @pytest.mark.integration
    @pytest.mark.skipif(
        sys.platform != "linux",
        reason="For simplicity, we only run the integration tests on Linux.",
    )
    def test_run_with_tools(self, tools):
        chat_generator = OllamaChatGenerator(model="llama3.2:3b", tools=tools)

        message = ChatMessage.from_user("What is the weather in Paris?")
        response = chat_generator.run([message])

        assert len(response["replies"]) == 1
        message = response["replies"][0]

        assert message.tool_calls
        tool_call = message.tool_call
        assert isinstance(tool_call, ToolCall)
        assert tool_call.tool_name == "weather"
        assert tool_call.arguments == {"city": "Paris"}