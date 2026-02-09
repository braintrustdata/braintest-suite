import random
import time
from braintrust import traced
from faker import Faker
fake = Faker()

QUERY_TYPES = ["factual", "coding", "analytical", "creative", "conversational"]

@traced
def _mock_llm(
    prompt: str, temperature: float = 0.7, max_tokens: int = None
) -> str:
    if max_tokens:
        num_sentences = max(1, max_tokens // 20)
    else:
        num_sentences = (
            random.randint(1, 8) if temperature > 0.5 else random.randint(2, 5)
        )

    response = " ".join([fake.sentence() for _ in range(num_sentences)])
    # time.sleep(random.randint(0,2))
    return response

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
            "output": "\n".join(
                [fake.sentence() for _ in range(random.randint(1, 4))]
            ),
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
            col: (
                fake.word()
                if random.random() > 0.5
                else random.randint(1, 1000)
            )
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

    if random.random() > 0.7:
        analysis["detailed_breakdown"] = _mock_llm(
            "Provide detailed analysis", temperature=0.3, max_tokens=200
        )

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
def _mock_synthesize_results(context: dict, analysis: dict = None) -> str:
    num_sources = len(context.get("sources", []))
    synthesis_prompt = f"Synthesize information from {num_sources} sources"

    if analysis:
        synthesis_prompt += f" with confidence {analysis['confidence']}"

    max_tokens = random.randint(150, 400)
    synthesized = _mock_llm(
        synthesis_prompt, temperature=0.5, max_tokens=max_tokens
    )

    return synthesized

@traced
def _mock_generate_response(
    query: str, context: dict = None, synthesis: str = None
) -> str:
    if synthesis:
        prompt = f"Based on synthesis: {synthesis[:100]}... answer: {query}"
        temperature = 0.6
    elif context:
        prompt = f"Using {len(context)} context items, answer: {query}"
        temperature = 0.7
    else:
        prompt = f"Directly answer: {query}"
        temperature = 0.8

    response = _mock_llm(
        prompt, temperature=temperature, max_tokens=random.randint(100, 300)
    )

    return response

@traced
def _mock_quality_check(response: str) -> dict:
    checks = {
        "length_appropriate": len(response.split()) > 10,
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
def _mock_refine_response(original_response: str, suggestions: list) -> str:
    refinement_prompt = f"Refine response with {len(suggestions)} suggestions"
    refined = _mock_llm(
        refinement_prompt, temperature=0.5, max_tokens=random.randint(100, 250)
    )

    return refined

@traced
def _mock_execute_workflow(query: str, plan: list, classification: dict) -> str:
    context = None
    analysis = None
    synthesis = None
    response = None

    for step in plan:
        if step == "validate_inputs":
            validation = _mock_validate_inputs(query)
            if not validation["is_safe"] or not validation["is_coherent"]:
                return f"Error: {', '.join(validation['issues'])}"

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

    return response or "Unable to generate response"

@traced
def mock_answer_question(query: str) -> str:
    classification = _mock_classify_query(query)

    if classification["complexity"] == "simple" and random.random() > 0.3:
        return _mock_generate_response(query)

    plan = _mock_create_plan(query, classification)

    response = _mock_execute_workflow(query, plan, classification)

    if classification["type"] == "coding" and random.random() > 0.6:
        code_result = _mock_execute_code("mock code snippet")
        if code_result["status"] == "success":
            response += f"\n\nCode execution: {code_result['output']}"

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
        print(f"Response length: {len(response)} characters")

        time.sleep(random.uniform(0.1, 0.5))