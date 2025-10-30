"""Chatbot page component backed by Azure OpenAI chat completions."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterable, Optional

import streamlit as st

openai_spec = importlib.util.find_spec("openai")
if openai_spec is not None:  # pragma: no cover - imported at runtime when available
    from openai import APIStatusError, AzureOpenAI  # type: ignore[import]
else:  # pragma: no cover - dependency optional for linting
    APIStatusError = Exception  # type: ignore[misc]
    AzureOpenAI = None  # type: ignore[assignment]


AZURE_DEPLOYMENT_ENV = "AZURE_OPENAI_CHAT_DEPLOYMENT"


@st.cache_resource(show_spinner=False)
def _create_azure_client() -> Optional[AzureOpenAI]:
    """Instantiate a cached Azure OpenAI client from environment variables."""

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")

    if not endpoint or not api_key or AzureOpenAI is None:
        return None

    return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)


def _initialize_chat_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Hi! I'm Doggo, your PawChain guide. Ask me anything about Arc credit flows or this dashboard.",
            }
        ]


def render_chatbot_page() -> None:
    """Render the chatbot page using Azure OpenAI completions, mirroring Streamlit's tutorial flow."""

    st.title("💬 PawChain Chatbot")
    st.caption(
        "Powered by Azure OpenAI chat completions and Streamlit's conversational components for a GPT-like experience."
    )

    client = _create_azure_client()
    if client is None:
        st.info(
            "Set environment variables `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, and optionally `AZURE_OPENAI_API_VERSION` "
            "inside `.env` to enable the chatbot."
        )

    _initialize_chat_state()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask Doggo anything about setup, credit scoring, or MCP tooling…"):
        _append_message("user", prompt)
        with st.chat_message("user"):
            st.markdown(prompt)

        if client is None:
            fallback = (
                "Azure OpenAI credentials are missing. Configure them to receive generated responses, or review the Intro page."
            )
            _append_message("assistant", fallback)
            with st.chat_message("assistant"):
                st.markdown(fallback)
            return

        deployment = os.getenv(AZURE_DEPLOYMENT_ENV)
        if not deployment:
            warning = (
                "Environment variable `AZURE_OPENAI_CHAT_DEPLOYMENT` is not set. Add it to `.env` with your deployed "
                "Azure OpenAI model name."
            )
            _append_message("assistant", warning)
            with st.chat_message("assistant"):
                st.warning(warning)
            return

        try:
            with st.chat_message("assistant"):
                stream = client.chat.completions.create(
                    model=deployment,
                    messages=[
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in st.session_state.messages
                    ],
                    stream=True,
                )
                assistant_reply = st.write_stream(_stream_chunks(stream))
        except APIStatusError as exc:  # pragma: no cover - surfaced via UI only
            assistant_reply = f"Azure OpenAI error: {exc.message}"
            st.error(assistant_reply)
        except Exception as exc:  # pragma: no cover - surfaced via UI only
            assistant_reply = f"Unexpected Azure OpenAI error: {exc}"
            st.error(assistant_reply)

        _append_message("assistant", assistant_reply)


def _stream_chunks(stream: Iterable) -> Iterable[str]:
    """Yield token deltas from the streaming Azure OpenAI response."""

    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


def _append_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})

