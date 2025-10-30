"""Streamlit dashboard for PawChain Capital credit insights."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import streamlit as st

from components.chatbot import render_chatbot_page
from components.intro import render_intro_page
from components.mcp_tools import render_mcp_tools_page
from components.navigation import render_navigation

dotenv_spec = importlib.util.find_spec("dotenv")
if dotenv_spec is not None:  # pragma: no cover - imported at runtime when available
    from dotenv import load_dotenv  # type: ignore[import]
else:  # pragma: no cover - dependency optional for linting
    load_dotenv = None  # type: ignore[assignment]


if load_dotenv:  # pragma: no cover - executed at runtime
    env_path = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(env_path)


st.set_page_config(page_title="Credit Dashboard", page_icon="🐶", layout="wide")

active_page = render_navigation()

if active_page == "Intro":
    render_intro_page()
elif active_page == "Chatbot":
    render_chatbot_page()
else:
    render_mcp_tools_page()

