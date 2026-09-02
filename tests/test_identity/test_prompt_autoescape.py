"""Regression tests for Jinja2 autoescape fix in identity/prompt.py.

Issue #850: autoescape=False allowed XSS in contexts where the rendered
prompt is displayed as HTML. The fix uses autoescape=True so all template
output is HTML-escaped at the Jinja2 level. Since the output is a plain-text
LLM prompt, escaped entities (``&lt;``, ``&amp;``) are decoded by the model
with no functional loss.
"""

from __future__ import annotations

from agentos.identity.prompt import _make_env, assemble_system_prompt
from agentos.identity.types import AgentIdentity, AgentProfile, SoulDocument


class TestMakeEnvAutoescape:
    """_make_env() must have autoescape enabled."""

    def test_autoescape_is_true(self) -> None:
        env = _make_env()
        assert env.autoescape is True


class TestSystemPromptEscaped:
    """Variables with HTML content must be escaped in the prompt output."""

    def test_script_tag_in_identity_name_is_escaped(self) -> None:
        """HTML-like variables must be escaped to prevent XSS."""
        profile = AgentProfile(
            agent_id="test",
            prompt_mode="full",
            identity=AgentIdentity(name="<script>alert('XSS')</script>"),
        )
        prompt = assemble_system_prompt(profile, tools=["read_file"])
        # The prompt is plain text, but variable values are HTML-escaped so
        # the output is safe if rendered in a web UI. The LLM can decode
        # entities with no functional loss.
        assert "&lt;script&gt;alert(&#39;XSS&#39;)&lt;/script&gt;" in prompt
        assert "<script>alert('XSS')</script>" not in prompt

    def test_soul_body_with_html_is_escaped(self) -> None:
        """Soul content with angle brackets must be HTML-escaped."""
        profile = AgentProfile(
            agent_id="test",
            prompt_mode="full",
            identity=AgentIdentity(
                name="Agent",
                soul=SoulDocument(body="You are <b>bold</b> and use <3 in code."),
            ),
        )
        prompt = assemble_system_prompt(profile, tools=["read_file"])
        assert "&lt;b&gt;bold&lt;/b&gt;" in prompt
        assert "&lt;3" in prompt
        assert "<b>bold</b>" not in prompt
