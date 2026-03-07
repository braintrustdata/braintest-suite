import random
import time
from braintrust import traced, current_span, JSONAttachment, init_logger
from faker import Faker
import yaml

fake = Faker()

MAX_SPAN_SIZE = 5 * 1024 * 1024  # 5MB
QUERY_TYPES = ["factual", "coding", "analytical", "creative", "conversational"]


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
            "output_size": len(text),
            "num_sentences": num_sentences,
            "llm_response": text,
        })
    return pool

print(f"Generating response pool messages")
_RESPONSE_POOL = _build_response_pool(
    config["loadtest"]["params"]["faker_pool_size"],
    config["loadtest"]["params"]["max_tokens"],
)
print(f"Pool messages generated")


@traced(notrace_io=True)
def _mock_llm() -> dict:
    span = current_span()
    max_tokens = config["loadtest"]["params"]["max_tokens"]
    output = random.choice(_RESPONSE_POOL)
    input_data = {"prompt": "Generate a mock llm response", "input_max_tokens": max_tokens}

    if output["output_size"] > MAX_SPAN_SIZE:
        span.log(
            input=input_data,
            output=JSONAttachment(data=output, filename="llm_response.json", pretty=True),
        )
    else:
        span.log(input=input_data, output=output)

    return output

@traced
def _mock_classify_query(query: str) -> dict:
    query_type = random.choice(QUERY_TYPES)
    complexity = random.choice(["simple", "moderate", "complex"])
    requires_tools = random.random() > 0.3

    return {
        "type": query_type,
        "complexity": complexity,
        "requires_tools": requires_tools,
        "intent": fake.catch_phrase(),
    }


@traced
def _mock_create_plan(query: str, classification: dict) -> list:
    plan_steps = []

    if classification["complexity"] == "simple":
        plan_steps = ["direct_response"]
    elif classification["complexity"] == "moderate":
        plan_steps = ["retrieve_context", "generate_response"]
    else:
        plan_steps = [
            "retrieve_context",
            "analyze_data",
            "synthesize_results",
            "generate_response",
        ]

    if random.random() > 0.7:
        plan_steps.insert(1, "validate_inputs")
    if random.random() > 0.6:
        plan_steps.append("quality_check")

    return plan_steps


@traced
def _mock_search_knowledge_base(query: str) -> list:
    num_results = random.randint(2, 8)
    results = []

    for i in range(num_results):
        results.append(
            {
                "id": fake.uuid4(),
                "content": fake.paragraph(nb_sentences=random.randint(2, 5)),
                "relevance_score": round(random.uniform(0.6, 0.99), 3),
                "source": fake.url(),
            }
        )

    return sorted(results, key=lambda x: x["relevance_score"], reverse=True)


@traced
def _mock_search_web(query: str) -> list:
    num_results = random.randint(3, 7)
    results = []

    for i in range(num_results):
        results.append(
            {
                "title": fake.catch_phrase(),
                "snippet": fake.paragraph(nb_sentences=random.randint(1, 3)),
                "url": fake.url(),
                "relevance": round(random.uniform(0.5, 0.95), 3),
            }
        )

    return results


@traced
def _mock_execute_code(code_snippet: str) -> dict:
    success = random.random() > 0.15

    if success:
        return {
            "status": "success",
            "output": "\n".join([fake.sentence() for _ in range(random.randint(1, 4))]),
            "execution_time_ms": random.randint(50, 500),
        }
    else:
        return {
            "status": "error",
            "error": f"{fake.word()}Error: {fake.sentence()}",
            "execution_time_ms": random.randint(10, 100),
        }


@traced
def _mock_query_database(sql_query: str) -> list:
    num_rows = random.randint(5, 50)
    columns = [fake.word() for _ in range(random.randint(3, 6))]

    results = []
    for _ in range(num_rows):
        row = {
            col: (fake.word() if random.random() > 0.5 else random.randint(1, 1000))
            for col in columns
        }
        results.append(row)

    return results


@traced
def _mock_retrieve_context(query: str, query_type: str) -> dict:
    context = {"sources": []}

    kb_results = _mock_search_knowledge_base(query)
    context["sources"].extend(kb_results[:3])

    if query_type == "factual" and random.random() > 0.4:
        web_results = _mock_search_web(query)
        context["web_results"] = web_results[:2]

    if query_type == "coding" and random.random() > 0.5:
        context["code_examples"] = [
            fake.paragraph() for _ in range(random.randint(1, 3))
        ]

    if query_type == "analytical" and random.random() > 0.6:
        db_results = _mock_query_database(f"SELECT * FROM data WHERE {fake.word()}")
        context["data"] = db_results[:10]

    return context


@traced
def _mock_analyze_data(context: dict) -> dict:
    analysis = {
        "summary": fake.paragraph(nb_sentences=random.randint(2, 4)),
        "key_points": [fake.sentence() for _ in range(random.randint(2, 5))],
        "confidence": round(random.uniform(0.7, 0.98), 3),
    }

    return analysis


@traced
def _mock_validate_inputs(query: str) -> dict:
    is_safe = random.random() > 0.05
    is_coherent = random.random() > 0.1

    validation = {"is_safe": is_safe, "is_coherent": is_coherent, "issues": []}

    if not is_safe:
        validation["issues"].append(f"Safety concern: {fake.sentence()}")
    if not is_coherent:
        validation["issues"].append(f"Coherence issue: {fake.sentence()}")

    return validation


@traced
def _mock_synthesize_results(context: dict, analysis: dict = None) -> dict:
    llm_output = _mock_llm()
    return {
        "output_size": llm_output.get("output_size"),
        "num_sentences": llm_output.get("num_sentences"),
    }


@traced
def _mock_generate_response(
    query: str, context: dict = None, synthesis: dict = None
) -> dict:
    llm_output = _mock_llm()
    return {
        "output_size": llm_output.get("output_size"),
        "num_sentences": llm_output.get("num_sentences"),
    }


@traced
def _mock_quality_check(response: dict) -> dict:
    output_size = response.get("output_size", 0)
    checks = {
        "length_appropriate": output_size > 100,
        "coherent": random.random() > 0.1,
        "factual": random.random() > 0.15,
        "helpful": random.random() > 0.2,
        "overall_score": round(random.uniform(0.7, 0.98), 3),
    }

    if checks["overall_score"] < 0.8:
        checks["needs_refinement"] = True
        checks["refinement_suggestions"] = [
            fake.sentence() for _ in range(random.randint(1, 3))
        ]
    else:
        checks["needs_refinement"] = False

    return checks


@traced
def _mock_refine_response(original_response: dict, suggestions: list) -> dict:
    llm_output = _mock_llm()
    return {
        "output_size": llm_output.get("output_size"),
        "num_sentences": llm_output.get("num_sentences"),
    }


@traced
def _mock_execute_workflow(query: str, plan: list, classification: dict) -> dict:
    context = None
    analysis = None
    synthesis = None
    response = None

    for step in plan:
        if step == "validate_inputs":
            validation = _mock_validate_inputs(query)
            if not validation["is_safe"] or not validation["is_coherent"]:
                return {"error": validation["issues"]}

        elif step == "retrieve_context":
            context = _mock_retrieve_context(query, classification["type"])

        elif step == "analyze_data":
            if context:
                analysis = _mock_analyze_data(context)

        elif step == "synthesize_results":
            if context:
                synthesis = _mock_synthesize_results(context, analysis)

        elif step == "direct_response":
            response = _mock_generate_response(query)

        elif step == "generate_response":
            response = _mock_generate_response(query, context, synthesis)

        elif step == "quality_check":
            if response:
                qc_results = _mock_quality_check(response)
                if qc_results.get("needs_refinement"):
                    response = _mock_refine_response(
                        response, qc_results.get("refinement_suggestions", [])
                    )

    return response or {"error": "Unable to generate response"}


@traced
def mock_answer_question(query: str) -> dict:
    classification = _mock_classify_query(query)

    if classification["complexity"] == "simple" and random.random() > 0.3:
        return _mock_generate_response(query)

    plan = _mock_create_plan(query, classification)

    response = _mock_execute_workflow(query, plan, classification)

    if classification["type"] == "coding" and random.random() > 0.6:
        code_result = _mock_execute_code("mock code snippet")
        if code_result["status"] == "success":
            response["code_execution"] = code_result["output"]

    return response


if __name__ == "__main__":
    query_templates = [
        lambda: fake.sentence(),
        lambda: f"How do I {fake.word()} {fake.word()}?",
        lambda: f"What is the {fake.word()} of {fake.word()}?",
        lambda: f"Explain {fake.catch_phrase()}",
        lambda: f"Write code to {fake.word()} {fake.word()}",
        lambda: f"Analyze {fake.word()} and provide {fake.word()}",
        lambda: f"Compare {fake.word()} and {fake.word()}",
    ]

    for i in range(50):
        query = random.choice(query_templates)()
        print(f"\n{'='*60}")
        print(f"Query {i+1}: {query}")
        print(f"{'='*60}")

        response = mock_answer_question(query)
        print(f"Response length: {response.get('output_size', 0)} characters")

        time.sleep(random.uniform(1, 5))
