import json
import os
import random
import yaml
from dotenv import load_dotenv
from faker import Faker
from braintrust import traced, current_span, start_span, JSONAttachment, init_logger

fake = Faker()

MAX_SPAN_SIZE = 3 * 1024 * 1024 # Above this will upload as attachment

_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the knowledge base for relevant information",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": "Execute a code snippet and return its output",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Query a database for structured data",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for current information",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def load_config() -> dict:
    with open("./braintest.yaml", "r") as f:
        config = yaml.safe_load(f)
    return config


config = load_config()


def _build_response_pool(pool_size: int, max_tokens: int) -> list:
    base_sentences = max_tokens // 20
    pool = []
    for _ in range(pool_size):
        num_sentences = max(1, int(base_sentences * random.uniform(0.8, 1.2)))
        text = fake.paragraph(nb_sentences=num_sentences)
        pool.append({
            "content": text,
            "num_sentences": num_sentences,
            "output_size": len(text),
        })
    return pool

print(f"Building faker message response pool to optimize")
_RESPONSE_POOL = _build_response_pool(
    config["loadtest"]["params"]["faker_pool_size"],
    config["loadtest"]["params"]["max_tokens"],
)
print(f"Pool generated")


@traced(type="tool")
def _mock_tool_execution(tool_name: str, arguments: dict) -> dict:
    if tool_name == "search_knowledge_base":
        return {
            "results": [
                {"id": fake.uuid4(), "content": fake.paragraph(), "score": round(random.uniform(0.6, 0.99), 3)}
                for _ in range(random.randint(2, 5))
            ]
        }
    elif tool_name == "execute_code":
        success = random.random() > 0.15
        return {
            "status": "success" if success else "error",
            "output": "\n".join(fake.sentence() for _ in range(random.randint(1, 4))) if success else fake.sentence(),
        }
    elif tool_name == "query_database":
        return {
            "rows": [
                {"id": i, "value": fake.word(), "count": random.randint(1, 1000)}
                for i in range(random.randint(2, 10))
            ]
        }
    elif tool_name == "search_web":
        return {
            "results": [
                {"title": fake.catch_phrase(), "snippet": fake.sentence(), "url": fake.url()}
                for _ in range(random.randint(3, 6))
            ]
        }
    return {"result": fake.sentence()}


@traced(type="llm", notrace_io=True)
def _mock_llm_call(messages: list, tools: list | None = None) -> dict:
    span = current_span()
    should_call_tool = bool(tools) and random.random() > 0.5
    model = random.choice(["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])

    if should_call_tool:
        tool = random.choice(tools)
        tool_call_id = f"call_{fake.uuid4()[:8]}"
        assistant_message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool["function"]["name"],
                        "arguments": json.dumps({"query": fake.sentence()}),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
        output_size = 0
    else:
        pool_entry = random.choice(_RESPONSE_POOL)
        assistant_message = {"role": "assistant", "content": pool_entry["content"]}
        finish_reason = "stop"
        output_size = pool_entry["output_size"]

    prompt_tokens = random.randint(100, 500)
    completion_tokens = max(1, output_size // 4)

    metadata = {"model": model, "finish_reason": finish_reason}
    if tools:
        metadata["tools"] = tools

    metrics = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tokens": prompt_tokens + completion_tokens,
    }

    if output_size > MAX_SPAN_SIZE:
        span.log(
            input=messages,
            output=JSONAttachment(data=assistant_message, filename="completion.json", pretty=True),
            metrics=metrics,
            metadata=metadata,
        )
    else:
        span.log(input=messages, output=assistant_message, metrics=metrics, metadata=metadata)

    return {
        "id": f"chatcmpl-{fake.uuid4()[:8]}",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": assistant_message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
    }


@traced(type="task")
def mock_multiturn_conversation(query: str) -> dict:
    num_turns = random.choice([2, 4])
    system_message = {"role": "system", "content": "You are a helpful assistant."}
    current_user_message = {"role": "user", "content": query}
    final_content = ""

    for turn_idx in range(num_turns):
        is_last_turn = turn_idx == num_turns - 1

        with start_span(f"chat_turn_{turn_idx + 1}") as turn_span:
            turn_span.log(input=current_user_message["content"])

            turn_context = [system_message, current_user_message]
            completion = _mock_llm_call(turn_context, tools=_TOOL_DEFINITIONS)
            assistant_message = completion["choices"][0]["message"]
            tool_calls = assistant_message.get("tool_calls")

            if tool_calls:
                follow_up_context = turn_context + [assistant_message]
                for tool_call in tool_calls:
                    tool_name = tool_call["function"]["name"]
                    arguments = json.loads(tool_call["function"]["arguments"])
                    tool_result = _mock_tool_execution(tool_name, arguments)
                    follow_up_context.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(tool_result),
                    })
                follow_up = _mock_llm_call(follow_up_context)
                final_message = follow_up["choices"][0]["message"]
            else:
                final_message = assistant_message

            final_content = final_message.get("content") or ""
            turn_span.log(
                output={
                    "output_size_bytes": len(final_content.encode("utf-8")),
                    "has_output": bool(final_content),
                    "used_tool_calls": bool(tool_calls),
                }
            )

        if not is_last_turn:
            current_user_message = {"role": "user", "content": fake.sentence()}

    return {"output_size": len(final_content), "num_turns": num_turns}


if __name__ == "__main__":
    load_dotenv()

    logger = init_logger(
        project=config["braintrust"]["project_name"],
        api_key=os.getenv("BRAINTRUST_API_KEY"),
        async_flush=True,
    )

    query_templates = [
        lambda: fake.sentence(),
        lambda: f"How do I {fake.word()} {fake.word()}?",
        lambda: f"What is the {fake.word()} of {fake.word()}?",
        lambda: f"Explain {fake.catch_phrase()}",
    ]

    for i in range(3):
        query = random.choice(query_templates)()
        print(f"\nRun {i + 1}: {query}")
        result = mock_multiturn_conversation(query)
        print(f"  turns={result['num_turns']}, output_size={result['output_size']}")

    logger.flush()
