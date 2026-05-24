"""Knowledge & Profile tab."""
from __future__ import annotations

import streamlit as st

from src.config import PROFILE_PATH, QA_BANK_PATH
from src.deliver.common import DashboardContext


def render(_ctx: DashboardContext) -> None:
    st.markdown('<div class="ja-eyebrow" style="margin-top:18px">05 / Configure</div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-section-title">Knowledge & Profile</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ja-note">These files drive the search, the scoring, and the tailoring. '
        'Edit them on disk and reload this page.</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ja-col-label">search_profile.yaml</div>', unsafe_allow_html=True)
    st.code(PROFILE_PATH.read_text(), language="yaml")

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
    st.markdown('<div class="ja-col-label">qa_bank.json</div>', unsafe_allow_html=True)
    st.code(QA_BANK_PATH.read_text(), language="json")
