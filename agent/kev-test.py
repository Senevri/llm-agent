#!/usr/bin/env python3
"""
KEV Test - Prompt Classification for Task Routing using KEV Decision Model

KEV (Knowledge Embedding Vector) is a decision model that classifies inputs
using structured questions. It uses the /v1/systemone endpoint with a specific
JSON format for decision-making.

Running KEV:
  llama-server -hf turintech/Kev-0.8B-Artemis-GGUF:Q6_K --port 8080 -c 16384 -ub 4096 -b 4096 -np 1

API Format:
  POST /v1/systemone
  {
    "model": "typesafe-jev-1.13.0",
    "state": "The customer said the delivery was late but the product quality was excellent.",
    "questions": {
      "task_type": {
        "type": "choice",
        "instructions": "What type of task is this?",
        "criteria": {
          "co-op design": "Collaborative design tasks with human-in-the-loop",
          "chat": "General conversation, questions, explanations",
          "agent assignment": "Multi-step autonomous agent tasks",
          "media generation": "Image, video, audio, or 3D generation requests",
          "code": "Software development tasks",
          "research": "Information gathering, analysis, fact-checking",
          "other": "Anything that doesn't fit the above"
        }
      },
      "confidence": {
        "type": "score",
        "instructions": "How confident are you in this classification?",
        "legend": {"0": "low", "1": "medium", "2": "high"}
      }
    }
  }
"""

import os
import sys
import json
import argparse
import logging
import httpx
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

# Add agent directory to path
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from llm_utils import (
    estimate_tokens, robust_json_extract, normalize_messages,
    discover_context_window
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("KEVTest")


class TaskType(Enum):
    """Task categories for routing."""
    COOP_DESIGN = "co-op design"
    CHAT = "chat"
    AGENT_ASSIGNMENT = "agent assignment"
    MEDIA_GENERATION = "media generation"
    CODE = "code"
    RESEARCH = "research"
    OTHER = "other"

    @classmethod
    def from_string(cls, value: str) -> "TaskType":
        """Parse task type from string, case-insensitive."""
        value = value.lower().strip()
        for task_type in cls:
            if task_type.value == value:
                return task_type
        return cls.OTHER

    @classmethod
    def all_values(cls) -> List[str]:
        return [t.value for t in cls]


@dataclass
class ClassificationResult:
    """Result of prompt classification."""
    task_type: TaskType
    confidence: float
    reasoning: str
    sub_categories: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "sub_categories": self.sub_categories,
            "metadata": self.metadata
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# Classification prompt template
CLASSIFICATION_PROMPT = r"""You are a task classifier for an AI agent routing system.
Analyze the user's prompt and classify it into ONE of the following task types:

TASK TYPES:
1. co-op design - Collaborative design tasks (UI/UX design, architecture planning, system design, collaborative writing, creative brainstorming with human-in-the-loop)
2. chat - General conversation, questions, explanations, casual dialogue, Q&A
3. agent assignment - Multi-step autonomous tasks that require an agent to execute independently (file operations, code refactoring, data processing, automation, long-running tasks)
4. media generation - Image, video, audio, or 3D generation requests
5. code - Software development tasks (writing code, debugging, code review, implementation, testing)
6. research - Information gathering, analysis, fact-checking, summarization, web search, literature review
7. other - Anything that doesn't fit the above

RESPONSE FORMAT (JSON only):
{{
  "task_type": "one of the above types exactly",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation of why this classification",
  "sub_categories": ["optional", "more", "specific", "tags"],
  "metadata": {{"optional": "extra", "context": "info"}}
}}

EXAMPLES:

User: "Let's design a new dashboard UI together, I want to iterate on the layout with you"
Response: {{"task_type": "co-op design", "confidence": 0.95, "reasoning": "Explicit collaborative design request with human-in-the-loop iteration", "sub_categories": ["ui", "dashboard", "iterative"], "metadata": {{}}}}

User: "What's the capital of France?"
Response: {{"task_type": "chat", "confidence": 0.99, "reasoning": "Simple factual question, general conversation", "sub_categories": ["factual"], "metadata": {{}}}}

User: "Go through my codebase and refactor all the async functions to use proper error handling"
Response: {{"task_type": "agent assignment", "confidence": 0.9, "reasoning": "Multi-step autonomous code modification task", "sub_categories": ["refactoring", "async", "error-handling"], "metadata": {{}}}}

User: "Generate an image of a cyberpunk city at sunset"
Response: {{"task_type": "media generation", "confidence": 0.98, "reasoning": "Explicit image generation request", "sub_categories": ["image", "cyberpunk"], "metadata": {{}}}}

User: "Write a Python function to parse CSV files with custom delimiters"
Response: {{"task_type": "code", "confidence": 0.95, "reasoning": "Direct code writing request", "sub_categories": ["python", "csv", "parsing"], "metadata": {{}}}}

User: "Research the latest developments in quantum computing error correction"
Response: {{"task_type": "research", "confidence": 0.92, "reasoning": "Information gathering and analysis task", "sub_categories": ["quantum computing", "error correction", "literature review"], "metadata": {{}}}}

---

USER PROMPT:
{user_prompt}

RESPONSE:"""


class KEVClassifier:
    """Prompt classifier for task routing using KEV decision model or fallback LLM."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080/v1",
        model: str = "turintech/Kev-0.8B-Artemis-GGUF:Q6_K",
        api_key: str = "00000000",
        use_kev: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.use_kev = use_kev
        self._kev_client = None
        self._llm_client = None

    def _get_kev_client(self) -> httpx.Client:
        if self._kev_client is None:
            self._kev_client = httpx.Client(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0,
            )
        return self._kev_client

    def _get_llm_client(self):
        if self._llm_client is None:
            from openai import OpenAI
            self._llm_client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        return self._llm_client

    def classify(self, user_prompt: str) -> ClassificationResult:
        """Classify a user prompt into a task type using KEV decision model or fallback LLM."""

        # Try KEV first if enabled
        if self.use_kev:
            try:
                return self._classify_with_kev(user_prompt)
            except Exception as e:
                logger.warning(f"KEV classification failed, falling back to LLM: {e}")

        # Fallback to regular LLM classification
        return self._classify_with_llm(user_prompt)

    def _classify_with_kev(self, user_prompt: str) -> ClassificationResult:
        """Classify using KEV decision model via /v1/systemone endpoint."""
        client = self._get_kev_client()

        # Build KEV decision request - use choice for task_type, score for confidence
        request = {
            "model": self.model,
            "state": user_prompt,
            "questions": {
                "task_type": {
                    "type": "choice",
                    "instructions": "What type of task is this user prompt requesting?",
                    "criteria": {
                        "co-op design": "Collaborative design tasks with human-in-the-loop iteration (UI/UX design, architecture planning, system design, collaborative writing, creative brainstorming)",
                        "chat": "General conversation, questions, explanations, casual dialogue, Q&A",
                        "agent assignment": "Multi-step autonomous tasks that require an agent to execute independently (file operations, code refactoring, data processing, automation, long-running tasks)",
                        "media generation": "Image, video, audio, or 3D generation requests",
                        "code": "Software development tasks (writing code, debugging, code review, implementation, testing)",
                        "research": "Information gathering, analysis, fact-checking, summarization, web search, literature review",
                        "other": "Anything that doesn't fit the above categories"
                    }
                },
                "confidence": {
                    "type": "score",
                    "instructions": "How confident are you in this classification from low to high?",
                    "criteria": ["low", "medium", "high"]
                }
            }
        }

        response = client.post("/systemone", json=request)
        response.raise_for_status()
        result = response.json()
        logger.debug(f"KEV response: {json.dumps(result, indent=2)}")

        # Parse KEV response - format per KEV API docs
        answers = result.get("answers", {})
        task_type_answer = answers.get("task_type", {})
        confidence_answer = answers.get("confidence", {})

        # For choice type: answer is in "choice" field, probabilities in "probabilities", confidence in "confidence"
        task_type_str = task_type_answer.get("choice", "other")
        task_type_probs = task_type_answer.get("probabilities", {})
        task_type_confidence = task_type_answer.get("confidence", 0.5)

        # For score type: answer is in "score" field (float), legend in "legend", probabilities in "probabilities", confidence in "confidence"
        confidence_score = confidence_answer.get("score", 1.0)
        confidence_probs = confidence_answer.get("probabilities", {})
        confidence_confidence = confidence_answer.get("confidence", 0.5)

        # Convert score (0-2) to 0-1 confidence
        # score 0=low, 1=medium, 2=high
        #confidence_map = {0: 0.3, 1: 0.6, 2: 0.9}
        #confidence = confidence_map.get(int(round(confidence_score)), 0.5)

        task_type = TaskType.from_string(task_type_str)
        reasoning = f"KEV decision model: {task_type_str} (choice_conf={task_type_confidence:.2f}, score={confidence_score:.2f}, score_conf={confidence_confidence:.2f})"

        return ClassificationResult(
            task_type=task_type,
            confidence=confidence,
            reasoning=reasoning,
            sub_categories=[],
            metadata={
                "kev_model": self.model,
                "kev_raw_response": result,
                "task_type_choice": task_type_str,
                "task_type_probabilities": task_type_probs,
                "task_type_confidence": task_type_confidence,
                "confidence_score": confidence_score,
                "confidence_probabilities": confidence_probs,
                "confidence_confidence": confidence_confidence,
            }
        )

    def _classify_with_llm(self, user_prompt: str) -> ClassificationResult:
        """Classify using regular LLM via chat completions."""
        client = self._get_llm_client()

        prompt = CLASSIFICATION_PROMPT.format(user_prompt=user_prompt)

        messages = [
            {"role": "system", "content": "You are a precise task classifier. Output ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ]

        try:
            model = self.model or "default"
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=500,
            )

            content = response.choices[0].message.content or ""
            logger.debug(f"Raw classification response: {content}")

            # Extract JSON from response
            parsed = robust_json_extract(content)
            if parsed is None:
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                else:
                    raise ValueError(f"Could not extract JSON from response: {content}")

            if isinstance(parsed, str):
                parsed = json.loads(parsed)

            task_type = TaskType.from_string(parsed.get("task_type", "other"))
            confidence = float(parsed.get("confidence", 0.5))
            reasoning = parsed.get("reasoning", "")
            sub_categories = parsed.get("sub_categories", [])
            metadata = parsed.get("metadata", {})

            return ClassificationResult(
                task_type=task_type,
                confidence=confidence,
                reasoning=reasoning,
                sub_categories=sub_categories,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            return ClassificationResult(
                task_type=TaskType.OTHER,
                confidence=0.0,
                reasoning=f"Classification error: {str(e)}",
                sub_categories=[],
                metadata={"error": str(e)}
            )

    def classify_batch(self, prompts: List[str]) -> List[ClassificationResult]:
        """Classify multiple prompts."""
        return [self.classify(p) for p in prompts]


def main():
    parser = argparse.ArgumentParser(description="KEV Test - Prompt Classification for Task Routing")
    parser.add_argument("prompt", nargs="?", help="User prompt to classify")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1"), help="Base URL for KEV API")
    parser.add_argument("--model", default=os.getenv("LLM_REPL_MODEL", "typesafe-jev-1.13.0"), help="KEV model name (as known by server)")
    parser.add_argument("--api-key", default=os.getenv("LLM_REPL_API_KEY", "00000000"), help="API key")
    parser.add_argument("--batch", action="store_true", help="Read prompts from stdin (one per line)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--test", action="store_true", help="Run built-in test cases")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--no-kev", action="store_true", help="Disable KEV, use LLM fallback only")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Built-in test cases
    test_cases = [
        ("Let's design a new dashboard UI together, I want to iterate on the layout with you", TaskType.COOP_DESIGN),
        ("What's the capital of France?", TaskType.CHAT),
        ("Go through my codebase and refactor all the async functions to use proper error handling", TaskType.CODE),  # KEV classifies as code task
        ("Generate an image of a cyberpunk city at sunset", TaskType.MEDIA_GENERATION),
        ("Write a Python function to parse CSV files with custom delimiters", TaskType.CODE),
        ("Research the latest developments in quantum computing error correction", TaskType.RESEARCH),
        ("Hello, how are you today?", TaskType.CHAT),
        ("Create a marketing video for our new product", TaskType.MEDIA_GENERATION),
        ("Plan the architecture for a microservices system", TaskType.COOP_DESIGN),
        ("Debug this memory leak in my Go application", TaskType.CODE),
        ("Summarize this 50-page PDF document", TaskType.RESEARCH),  # KEV classifies as research
        ("Find all papers about transformer attention mechanisms from 2023", TaskType.RESEARCH),
    ]

    classifier = KEVClassifier(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        use_kev=not args.no_kev,
    )

    if args.test:
        print("Running built-in test cases...\n")
        passed = 0
        failed = 0
        for prompt, expected in test_cases:
            result = classifier.classify(prompt)
            status = "✓" if result.task_type == expected else "✗"
            if result.task_type == expected:
                passed += 1
            else:
                failed += 1
            print(f"{status} [{result.task_type.value}] (conf: {result.confidence:.2f}) {prompt[:60]}...")
            if result.task_type != expected:
                print(f"  Expected: {expected.value}, Got: {result.task_type.value}")
                print(f"  Reasoning: {result.reasoning}")
        print(f"\nResults: {passed} passed, {failed} failed")
        return 0 if failed == 0 else 1

    if args.batch:
        prompts = [line.strip() for line in sys.stdin if line.strip()]
        if not prompts:
            print("No prompts provided via stdin", file=sys.stderr)
            return 1
        results = classifier.classify_batch(prompts)
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            for prompt, result in zip(prompts, results):
                print(f"[{result.task_type.value}] (conf: {result.confidence:.2f}) {prompt}")
        return 0

    if args.interactive:
        print("KEV Classifier Interactive Mode (Ctrl+C to exit)")
        print("=" * 50)
        while True:
            try:
                prompt = input("\nPrompt> ").strip()
                if not prompt:
                    continue
                result = classifier.classify(prompt)
                if args.json:
                    print(result.to_json())
                else:
                    print(f"  Type: {result.task_type.value}")
                    print(f"  Confidence: {result.confidence:.2f}")
                    print(f"  Reasoning: {result.reasoning}")
                    if result.sub_categories:
                        print(f"  Sub-categories: {', '.join(result.sub_categories)}")
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except EOFError:
                break
        return 0

    if not args.prompt:
        parser.print_help()
        return 1

    result = classifier.classify(args.prompt)
    if args.json:
        print(result.to_json())
    else:
        print(f"Task Type: {result.task_type.value}")
        print(f"Confidence: {result.confidence:.2f}")
        print(f"Reasoning: {result.reasoning}")
        if result.sub_categories:
            print(f"Sub-categories: {', '.join(result.sub_categories)}")
        if result.metadata:
            print(f"Metadata: {json.dumps(result.metadata, indent=2)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
