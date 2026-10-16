import json
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.agents.demo_fixtures import select_fixture
from app.agents.failures import provider_failure
from app.agents.instructions import system_instructions
from app.agents.pacing import endpoint_pacer
from app.config.settings import Settings
from app.models.schemas import Edit, Patch, Plan, Review

T = TypeVar("T", bound=BaseModel)


class Model(Protocol):
    def generate(self, schema: type[T], payload: dict) -> tuple[T, dict]: ...


class ModelFailure(ValueError):
    def __init__(self, message: str, stats: dict):
        super().__init__(message)
        self.stats = stats


class MockModel:
    """Fixture-specific deterministic adapter. Unsupported bugs fail explicitly."""

    def generate(self, schema: type[T], payload: dict) -> tuple[T, dict]:
        fixture = (
            select_fixture(payload.get("issue_description", "expired"))
            if schema in {Plan, Patch}
            else None
        )
        if schema is Plan:
            value = Plan(
                issue_summary=payload["issue_description"],
                suspected_modules=[fixture.module],
                search_strategy=list(fixture.search_terms),
                repair_steps=[
                    f"Apply explicit demo repair in {fixture.module}",
                    "Add regression test",
                ],
                validation_strategy=["pytest tests", "independent acceptance test"],
            )
        elif schema is Patch:
            context = payload.get("context", "")
            if fixture.old not in context:
                raise ValueError("Mock fixture precondition not found in retrieved context")
            value = Patch(
                rationale=f"Explicit demo fixture: repair {fixture.module}",
                edits=[
                    Edit(
                        path=fixture.module,
                        old=fixture.old,
                        new=fixture.new,
                    ),
                    Edit(
                        path=fixture.regression_path,
                        old="",
                        new=fixture.regression_code,
                    ),
                ],
            )
        elif schema is Review:
            ok = (
                payload["test_result"]["status"] == "passed"
                and bool(payload["diff"])
                and "+def test_" in payload["diff"]
            )
            value = Review(
                approved=ok,
                summary="Deterministic fixture checks; no semantic LLM review",
                concerns=[] if ok else ["Need passing tests and regression coverage"],
            )
        else:
            raise ValueError("Unsupported schema")
        return value, {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "adapter": "mock",
            "duration_seconds": 0,
        }


class LiveModel:
    def __init__(self, settings: Settings):
        from langchain_openai import ChatOpenAI

        self.model_name = settings.model_name
        self.pacer = endpoint_pacer(settings.model_base_url)
        self.min_interval = settings.model_min_interval
        self.client = ChatOpenAI(
            model=settings.model_name,
            temperature=0,
            timeout=settings.model_timeout,
            max_retries=1,
            base_url=settings.model_base_url,
            api_key=settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
        )

    def generate(self, schema: type[T], payload: dict) -> tuple[T, dict]:
        started = time.monotonic()
        stats = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "adapter": "live",
            "usage_complete": True,
            "model_requested": self.model_name,
            "rate_limit_wait_seconds": 0.0,
        }
        messages = [
            (
                "system",
                system_instructions(schema.__name__),
            ),
            ("human", json.dumps(payload, ensure_ascii=False)),
        ]
        for attempt in range(2):
            stats["rate_limit_wait_seconds"] += self.pacer.wait(self.min_interval)
            stats["calls"] += 1
            try:
                response = self.client.with_structured_output(
                    schema, method="function_calling", include_raw=True
                ).invoke(messages)
            except Exception as exc:
                stats["usage_complete"] = False
                stats["duration_seconds"] = time.monotonic() - started
                stats["failure"] = provider_failure(exc)
                raise ModelFailure(f"Model request failed: {type(exc).__name__}", stats) from exc
            usage = response["raw"].usage_metadata or {}
            metadata = getattr(response["raw"], "response_metadata", {}) or {}
            stats["model_reported"] = metadata.get("model_name") or metadata.get("model")
            stats["provider_response_id"] = metadata.get("id")
            stats["usage_complete"] &= bool(usage)
            stats["input_tokens"] += usage.get("input_tokens", 0)
            stats["output_tokens"] += usage.get("output_tokens", 0)
            if response["parsed"] is not None:
                stats["duration_seconds"] = time.monotonic() - started
                try:
                    return schema.model_validate(response["parsed"]), stats
                except ValueError:
                    pass
            messages.append(
                (
                    "human",
                    "Previous output failed schema validation. Return valid "
                    f"{schema.__name__} structured output; attempt {attempt + 1}.",
                )
            )
        stats["duration_seconds"] = time.monotonic() - started
        raise ModelFailure("Model output failed schema validation twice", stats)


def create_model(settings: Settings) -> Model:
    return MockModel() if settings.model_mode == "mock" else LiveModel(settings)
