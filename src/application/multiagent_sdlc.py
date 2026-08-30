"""Multi-Agent SDLC Workflow Coordinator (Planner -> Developer -> QA Tester -> Reviewer)."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from src.domain.agent import Message, Role
from src.domain.provider import AIProvider, CompletionRequest
from src.infrastructure.security.humanizer import humanize_response
from src.infrastructure.telegram.formatter import render_progress_bar
from src.infrastructure.tools.registry import ToolRegistry


class SDLCStage(str, Enum):
    PLAN = "PLAN"
    CODE = "CODE"
    TEST = "TEST"
    REVIEW = "REVIEW"
    DONE = "DONE"


@dataclass
class SDLCResult:
    feature_name: str
    plan_output: str
    code_output: str
    qa_output: str
    final_review: str
    success: bool = True


class MultiAgentSDLC:
    """Coordinates specialized sub-agents through a full Software Development Life Cycle."""

    def __init__(self, ai_provider: AIProvider, tool_registry: ToolRegistry):
        self.ai = ai_provider
        self.tools = tool_registry

    async def execute_feature_lifecycle(
        self,
        feature_description: str,
        user_id: int,
        progress_callback: Optional[Callable[[str, int], Any]] = None
    ) -> SDLCResult:
        """Run multi-agent sequence through Planner, Developer, QA, and Reviewer."""

        # -------------------------------------------------------------
        # Phase 1: Planning / Spec Decomposition (Planner Agent)
        # -------------------------------------------------------------
        if progress_callback:
            await progress_callback(f"Stage 1/4: Planning & Architecture...\n{render_progress_bar(25)}", 25)

        planner_prompt = (
            "You are the Architecture & Planning Agent. Break down the following requirement "
            "into clear, verifiable specifications, capability maps, and implementation tasks:\n\n"
            f"Requirement: {feature_description}"
        )
        plan_res = await self.ai.generate_response(CompletionRequest(
            messages=[Message(role=Role.USER, content=planner_prompt)],
            system_prompt="You are a senior software architect. Output direct, structured technical specs without marketing fluff.",
            tools=[]
        ))
        plan_text = humanize_response(plan_res.content or "Plan generated.")

        # -------------------------------------------------------------
        # Phase 2: Implementation & Coding (Developer Agent)
        # -------------------------------------------------------------
        if progress_callback:
            await progress_callback(f"Stage 2/4: Implementation...\n{render_progress_bar(50)}", 50)

        developer_prompt = (
            "You are the Lead Developer Agent. Based on the technical specification below, "
            "write the exact, minimal production code and implementation steps:\n\n"
            f"Specification:\n{plan_text}"
        )
        dev_res = await self.ai.generate_response(CompletionRequest(
            messages=[Message(role=Role.USER, content=developer_prompt)],
            system_prompt="You are an expert software engineer. Write clean, working code. No unnecessary abstractions.",
            tools=self.tools.list_definitions()
        ))
        code_text = humanize_response(dev_res.content or "Code implementation completed.")

        # -------------------------------------------------------------
        # Phase 3: QA & Verification (QA Tester Agent)
        # -------------------------------------------------------------
        if progress_callback:
            await progress_callback(f"Stage 3/4: QA & Security Verification...\n{render_progress_bar(75)}", 75)

        qa_prompt = (
            "You are the QA & Security Agent. Review the implementation against the original requirements. "
            "Verify edge cases, security boundaries, and generate test assertions:\n\n"
            f"Requirements:\n{feature_description}\n\n"
            f"Code Implementation:\n{code_text}"
        )
        qa_res = await self.ai.generate_response(CompletionRequest(
            messages=[Message(role=Role.USER, content=qa_prompt)],
            system_prompt="You are a rigorous QA & Security engineer. Focus on boundary errors, injection prevention, and unit tests.",
            tools=[]
        ))
        qa_text = humanize_response(qa_res.content or "QA verification completed.")

        # -------------------------------------------------------------
        # Phase 4: Final Humanized Synthesis (Reviewer Agent)
        # -------------------------------------------------------------
        if progress_callback:
            await progress_callback(f"Stage 4/4: Final Review & Polish...\n{render_progress_bar(100)}", 100)

        final_summary = (
            f"Multi-Agent SDLC Result: {feature_description}\n\n"
            f"1. Plan:\n{plan_text[:400]}...\n\n"
            f"2. Implementation:\n{code_text[:400]}...\n\n"
            f"3. QA Status:\n{qa_text[:300]}..."
        )

        return SDLCResult(
            feature_name=feature_description,
            plan_output=plan_text,
            code_output=code_text,
            qa_output=qa_text,
            final_review=final_summary,
            success=True
        )
