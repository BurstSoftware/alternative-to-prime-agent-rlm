"""Prime Agent Harness – Streamlit edition (NVIDIA API key + paste skills JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import streamlit as st

from harness import HarnessEntry, Kind, get_harness

st.set_page_config(page_title="Prime Agent Harness", page_icon="🧠", layout="wide")

# ---------- session state ----------
if "nvidia_key" not in st.session_state:
    st.session_state.nvidia_key = ""
if "model" not in st.session_state:
    st.session_state.model = "meta/llama-3.1-70b-instruct"
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------- sidebar ----------
with st.sidebar:
    st.header("⚙️ Configuration")
    st.session_state.nvidia_key = st.text_input(
        "NVIDIA API Key",
        value=st.session_state.nvidia_key,
        type="password",
        help="Get one at https://build.nvidia.com (starts with nvapi-)",
    )
    st.session_state.model = st.text_input("Model", value=st.session_state.model)

    scope = st.radio("Harness scope", ["local", "global"], horizontal=True)
    harness = get_harness(global_=(scope == "global"))

    st.divider()
    st.caption("State file: " + str(harness.state_file.resolve()))
    if st.button("🔄 Reload from disk"):
        harness.load()
        st.rerun()

# ---------- helpers ----------
def call_nvidia(system: str, user: str) -> str:
    if not st.session_state.nvidia_key:
        return "⚠️ Please enter your NVIDIA API key in the sidebar."
    headers = {
        "Authorization": f"Bearer {st.session_state.nvidia_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": st.session_state.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ NVIDIA API error: {e}"

def build_system_prompt(h) -> str:
    parts = ["You are a helpful agent that uses the following persistent context."]
    for kind in ("prompt", "memory", "skill"):
        for e in h.list(kind):  # type: ignore
            parts.append(f"\n### {kind.upper()}: {e.title}\n{e.content}")
            if e.reference:
                parts.append(f"Reference: {json.dumps(e.reference)}")
    return "\n".join(parts)

# ---------- main tabs ----------
tab_overview, tab_skills, tab_crud, tab_chat, tab_refine = st.tabs(
    ["📋 Overview", "📥 Paste Skills JSON", "✏️ CRUD", "💬 Chat with NVIDIA", "🔧 Refinements"]
)

with tab_overview:
    st.subheader("Current harness inventory")
    st.code(harness.overview(), language="text")
    st.download_button(
        "Download harness_state.json",
        data=harness.state_file.read_text() if harness.state_file.exists() else "{}",
        file_name=harness.state_file.name,
    )

with tab_skills:
    st.subheader("Paste agent skills as JSON")
    st.markdown(
        """
        Paste either a single skill object or an array of skill objects.
        Minimal shape:
        ```json
        {
          "title": "Document search",
          "content": "Search indexed documents…",
          "path": "retrieval",
          "reference": {"type": "python", "import": "…", "callable": "…"},
          "arguments": {"query": {"type": "string", "required": true}}
        }
        ```
        """
    )
    raw = st.text_area("Skills JSON", height=260, placeholder='[{"title": "…", "content": "…"}]')
    if st.button("Import skills", type="primary"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                st.error("Expected object or array")
            else:
                created = 0
                for item in data:
                    title = item.get("title") or item.get("id") or "untitled"
                    content = item.get("content", "")
                    harness.upsert(
                        "skill",
                        title=title,
                        content=content,
                        path=item.get("path", "general"),
                        reference=item.get("reference", {}),
                        arguments=item.get("arguments", {}),
                        metadata=item.get("metadata", {}),
                    )
                    created += 1
                st.success(f"Imported / upserted {created} skill(s)")
                st.rerun()
        except Exception as e:
            st.error(f"Parse / import failed: {e}")

with tab_crud:
    st.subheader("Create / edit / delete entries")
    kind: Kind = st.selectbox("Kind", ["prompt", "memory", "skill", "subagent"])  # type: ignore
    entries = harness.list(kind)
    selected = st.selectbox(
        "Existing (or leave blank to create)",
        [""] + [f"{e.id} – {e.title}" for e in entries],
    )
    eid = selected.split(" – ")[0] if selected else ""
    existing = harness.get(kind, eid) if eid else None

    title = st.text_input("Title", value=existing.title if existing else "")
    content = st.text_area("Content", value=existing.content if existing else "", height=150)
    path = st.text_input("Path", value=existing.path if existing else "general")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Create / Upsert", type="primary"):
            if not title.strip():
                st.warning("Title required")
            else:
                harness.upsert(kind, title=title.strip(), content=content, path=path)
                st.success("Saved")
                st.rerun()
    with col2:
        if existing and st.button("Delete", type="secondary"):
            harness.delete(kind, existing.id)
            st.success("Deleted")
            st.rerun()
    with col3:
        if existing:
            st.caption(f"v{existing.version}  updated {existing.updated_at}")

with tab_chat:
    st.subheader("Chat (context from current harness)")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask the agent…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        system = build_system_prompt(harness)
        answer = call_nvidia(system, prompt)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"):
            st.markdown(answer)

with tab_refine:
    st.subheader("Record a refinement")
    trigger = st.text_input("Trigger / problem observed")
    changes = st.text_area("Changes made (one per line)")
    evidence = st.text_input("Evidence (optional)")
    outcome = st.text_input("Outcome (optional)")
    if st.button("Record refinement"):
        if trigger and changes.strip():
            harness.record_refinement(
                trigger=trigger,
                changes=[c.strip() for c in changes.splitlines() if c.strip()],
                evidence=evidence or None,
                outcome=outcome or None,
            )
            st.success("Recorded")
            st.rerun()
        else:
            st.warning("Trigger and at least one change required")

st.caption("Prime Agent Harness – Streamlit edition • NVIDIA API • no MCP")
