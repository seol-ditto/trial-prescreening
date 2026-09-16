# -*- coding: utf-8 -*-
"""
CRC 프리스크리닝 자동화 - 데모 화면
====================================
실행: streamlit run streamlit_app.py

미리 screening_engine.py를 돌려서 screening_results.json을 만들어두면 그걸 불러와서 보여주고,
없으면 사이드바에서 API 키를 입력해 그 자리에서 바로 돌릴 수 있게 해뒀다(라이브 데모용).
"""

import json
import os
import streamlit as st

import screening_engine as engine

st.set_page_config(page_title="프리스크리닝 자동화", layout="wide")

STATUS_COLOR = {"적격": "🟢", "보류": "🟡", "부적격": "⚪"}
CHECK_COLOR = {"충족": "🟢", "위반": "🔴", "불확실": "🟡"}


# ----------------------------------------------------------------------
# 데이터 로드
# ----------------------------------------------------------------------
@st.cache_data
def load_precomputed():
    if os.path.exists(engine.OUTPUT_JSON):
        with open(engine.OUTPUT_JSON, encoding="utf-8") as f:
            return json.load(f)
    return None


def run_live(api_key: str):
    os.environ["ANTHROPIC_API_KEY"] = api_key
    with open(engine.CRITERIA_PATH, encoding="utf-8") as f:
        criteria = json.load(f)
    import csv
    with open(engine.PATIENTS_CSV, encoding="utf-8-sig") as f:
        patients = list(csv.DictReader(f))

    detailed = []
    progress = st.progress(0, text="환자 스크리닝 중...")
    for i, p in enumerate(patients):
        result = engine.screen_patient(p, criteria)
        detailed.append({**p, "ai_verdict": result["verdict"], "checks": result["checks"]})
        progress.progress((i + 1) / len(patients), text=f"{p['patient_id']} 처리 중... ({i+1}/{len(patients)})")
    progress.empty()
    return {"trial_name": criteria["trial_name"], "patients": detailed}


# ----------------------------------------------------------------------
# 사이드바
# ----------------------------------------------------------------------
st.sidebar.title("⚙️ 설정")
data = load_precomputed()

if data is None:
    st.sidebar.warning("미리 계산된 결과가 없습니다. API 키를 입력하고 지금 실행하세요.")
    api_key = st.sidebar.text_input("Anthropic API Key", type="password")
    if st.sidebar.button("지금 스크리닝 실행", disabled=not api_key):
        data = run_live(api_key)
        st.session_state["data"] = data
    data = st.session_state.get("data")
else:
    st.sidebar.success(f"불러온 결과: {len(data['patients'])}명")
    if st.sidebar.button("🔄 다시 실행 (API 키 필요)"):
        api_key = st.sidebar.text_input("Anthropic API Key", type="password", key="rerun_key")
        if api_key:
            data = run_live(api_key)

if not data:
    st.info("왼쪽에서 API 키를 입력하고 스크리닝을 실행해주세요.")
    st.stop()

trial_name = data["trial_name"]
patients = data["patients"]

# ----------------------------------------------------------------------
# 헤더 + 요약
# ----------------------------------------------------------------------
st.title("🏥 내일 방문 예정 환자 프리스크리닝")
st.caption(f"임상시험: {trial_name}")

n_eligible = sum(1 for p in patients if p["ai_verdict"] == "적격")
n_pending = sum(1 for p in patients if p["ai_verdict"] == "보류")
n_ineligible = sum(1 for p in patients if p["ai_verdict"] == "부적격")

c1, c2, c3, c4 = st.columns(4)
c1.metric("전체 방문 예정 환자", f"{len(patients)}명")
c2.metric("🟢 적격", f"{n_eligible}명")
c3.metric("🟡 보류 (직접 확인 필요)", f"{n_pending}명")
c4.metric("⚪ 부적격", f"{n_ineligible}명")

st.divider()

# ----------------------------------------------------------------------
# 리스트 뷰
# ----------------------------------------------------------------------
st.subheader("환자 목록")

filter_option = st.radio("필터", ["전체", "적격만", "보류만"], horizontal=True)
filtered = patients
if filter_option == "적격만":
    filtered = [p for p in patients if p["ai_verdict"] == "적격"]
elif filter_option == "보류만":
    filtered = [p for p in patients if p["ai_verdict"] == "보류"]

for p in filtered:
    with st.container(border=True):
        col1, col2, col3 = st.columns([1, 3, 1])
        with col1:
            st.markdown(f"### {STATUS_COLOR[p['ai_verdict']]} {p['ai_verdict']}")
            st.caption(p["patient_id"])
        with col2:
            st.write(f"**{p['age']}세 / {p['sex']} / NYHA {p['nyha_class']}**")
            uncertain_or_failed = [c for c in p["checks"] if c["status"] != "충족"]
            if uncertain_or_failed:
                st.caption(" · ".join(f"{c['description']} → {c['status']}" for c in uncertain_or_failed[:2]))
            else:
                st.caption("모든 기준 충족")
        with col3:
            with st.popover("상세 판단 근거 보기"):
                st.markdown(f"**{p['patient_id']} 상세**")
                st.write(f"ECHO: {p['echo_report']}")
                st.write(f"EKG: {p['ekg_finding']}")
                st.write(f"CRC 메모: {p['crc_note']}")
                st.divider()
                for c in p["checks"]:
                    st.markdown(f"{CHECK_COLOR[c['status']]} **{c['description']}** — {c['status']}")
                    if c["evidence"]:
                        st.caption(f"근거: {c['evidence']}")
                    if c["explanation"]:
                        st.caption(f"설명: {c['explanation']}")

                if p["ai_verdict"] == "적격":
                    st.divider()
                    memo = (
                        f"[교수님 전달용 메모]\n"
                        f"{p['patient_id']} ({p['age']}세/{p['sex']}, NYHA {p['nyha_class']}) - "
                        f"{trial_name} 참여 가능 후보로 확인됨.\n"
                        f"근거: LVEF·NYHA·GDMT 복용기간 등 선정기준 충족, 제외기준 해당사항 없음.\n"
                        f"※ AI 프리스크리닝 결과이며 최종 확인 및 동의서 절차는 별도 진행 필요."
                    )
                    st.text_area("📋 교수님께 전달할 메모 (복사해서 사용하세요)", memo, height=120)

st.divider()
st.caption("※ 본 화면은 가상 환자 데이터를 이용한 데모입니다. 실제 환자 데이터는 사용되지 않았습니다.")
