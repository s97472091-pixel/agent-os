"""Regression tests for Jinja2 autoescape fix in identity/prompt.py.

Issue #850: autoescape=False allowed XSS in contexts where the rendered
prompt is displayed as HTML. The fix uses select_autoescape(["html", "xml"])
so HTML templates are autoescaped by default while plain-text .j2 prompt
templates are not (escaping would corrupt the LLM prompt text).
"""

from __future__ import annotations

from agentos.identity.prompt import _make_env, assemble_system_prompt
from agentos.identity.types import AgentProfile


class TestMakeEnvAutoescape:
    """_make_env() must use select_autoescape so .html files are escaped."""

    def test_autoescapes_html_extension(self) -> None:
        env = _make_env()
        autoescape = env.autoescape
        # autoescape is a callable when select_autoescape is used
        if callable(autoescape):
            assert autoescape("foo.html") is True
            assert autoescape("foo.xml") is True
        else:
            assert autoescape is True, "expected autoescape for .html files"

    def test_does_not_autoescape_j2_extension(self) -> None:
        env = _make_env()
        autoescape = env.autoescape
        # .j2 templates are plain text — autoescaping would corrupt the prompt
        assert autoescape is not True, "bare True would escape .j2 output"
        if callable(autoescape):
            assert autoescape("system_prompt.j2") is False
            assert autoescape("foo.j2") is False


class TestSystemPromptNotEscaped:
    """The system prompt (plain-text .j2) must not be HTML-escaped."""

    def test_plain_text_variable_not_escaped(self) -> None:
        """Variables with HTML-like content must pass through unescaped."""
        from agentos.identity.types import AgentIdentity

        prompt = assemble_system_prompt(
            AgentProfile(
                agent_id="test",
                prompt_mode="full",
                identity=AgentIdentity(name="<script>alert('XSS')</script>"),
            ),
            tools=["read_file"],
        )
        # The prompt is plain text, not HTML — <script> must survive unescaped
        # so the LLM sees it literally (it is not rendered in a browser here).
        assert "<script>alert('XSS')</script>" in prompt
        # If autoescaping were applied, &lt;script&gt; would appear instead.
        assert "&lt;script&gt;" not in prompt

    def test_soul_body_with_html_passes_through(self) -> None:
        """Soul content with angle brackets must not be HTML-escaped."""
        from agentos.identity.types import AgentIdentity, AgentProfile, SoulDocument

        profile = AgentProfile(
            agent_id="test",
            prompt_mode="full",
            identity=AgentIdentity(
                name="Agent",
                soul=SoulDocument(body="You are <b>bold</b> and use <3 in code."),
            ),
        )
        prompt = assemble_system_prompt(profile, tools=["read_file"])
        # Plain-text prompt should preserve the soul content as-is.
        assert "<b>bold</b>" in prompt
        assert "&lt;b&gt;bold&lt;/b&gt;" not in prompt
