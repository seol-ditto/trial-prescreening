# -*- coding: utf-8 -*-
"""
CRC 프리스크리닝 자동화 - 데모 화면
====================================
실행: streamlit run streamlit_app.py

미리 screening_engine.py를 돌려서 screening_results.json을 만들어두면 그걸 불러와서 보여주고,
없으면 사이드바에서 API 키를 입력해 그 자리에서 바로 돌릴 수 있게 해뒀다(라이브 데모용).
"""

import io
import json
import os
import streamlit as st
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader

import screening_engine as engine

st.set_page_config(page_title="프리스크리닝 자동화", layout="wide")

STATUS_COLOR = {"적격": "🟢", "보류": "🟡", "부적격": "⚪"}
CHECK_COLOR = {"충족": "🟢", "위반": "🔴", "불확실": "🟡"}

# ----------------------------------------------------------------------
# 엑셀 업로드용 컬럼 매핑
# 실제 워크플로우: "외래예약 환자 리스트"(PHIS, 환자번호+인적사항)와
# "검사수치 리스트"(의무기록팀에 요청, 환자번호+검사결과)가 서로 다른 엑셀로 따로 나옴.
# 두 파일을 각각 업로드하면 "환자번호" 기준으로 자동 매칭(join)해서 하나로 합친다.
# ----------------------------------------------------------------------
APPT_COLUMN_MAP = {  # 외래예약 환자 리스트
    "환자번호": "patient_id",
    "나이": "age",
    "성별": "sex",
    "NYHA": "nyha_class",
    "GDMT복용주수": "gdmt_weeks",
    "임신수유여부": "pregnancy",
}

LABS_COLUMN_MAP = {  # 검사수치 리스트 (의무기록팀 제공)
    "환자번호": "patient_id",
    "ECHO소견": "echo_report",
    "EKG소견": "ekg_finding",
    "최근MI뇌졸중": "recent_mi_stroke",
    "판막질환": "valve_disease",
    "eGFR": "egfr",
    "CRC메모": "crc_note",
}


def _make_template(column_map: dict, example_row: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "환자목록"
    ws.append(list(column_map.keys()))
    ws.append(example_row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_appointment_template() -> bytes:
    return _make_template(APPT_COLUMN_MAP, ["12345678", 68, "남", "III", 8, "N/A"])


def make_labs_template() -> bytes:
    return _make_template(LABS_COLUMN_MAP, [
        "12345678",
        "2026-08-10 시행. LVEF 32%, 좌심실 확장 소견, 국소벽운동 이상 없음.",
        "정상 동리듬(NSR), 특이 부정맥 소견 없음.",
        "없음", "없음", 55, "복약순응도 양호. 지난달 ARNI 증량함.",
    ])


def _normalize_patient_id(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    return str(val).strip()


def read_excel_rows(uploaded_file, column_map: dict) -> list:
    """엑셀을 열어서 column_map(한글 헤더 -> 내부 필드명)에 따라 dict 목록으로 변환."""
    wb = load_workbook(uploaded_file, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("빈 엑셀 파일입니다.")

    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    missing_cols = [c for c in column_map if c not in header]
    if missing_cols:
        raise ValueError(f"템플릿에 있는 컬럼이 빠져있습니다: {', '.join(missing_cols)}")
    col_idx = {c: header.index(c) for c in column_map}

    parsed = []
    for row in rows[1:]:
        if row is None or all(v is None for v in row):
            continue
        p = {}
        for kr_col, field in column_map.items():
            idx = col_idx[kr_col]
            val = row[idx] if idx < len(row) else None
            p[field] = _normalize_patient_id(val) if field == "patient_id" else ("" if val is None else val)
        parsed.append(p)
    return parsed


def merge_by_patient_id(*row_lists: list) -> dict:
    """여러 엑셀에서 읽은 row 목록들을 환자번호(patient_id) 기준으로 병합."""
    merged = {}
    for rows in row_lists:
        for row in rows:
            pid = row.get("patient_id", "")
            if not pid:
                continue
            merged.setdefault(pid, {"patient_id": pid})
            merged[pid].update({k: v for k, v in row.items() if k != "patient_id" and v != ""})
    return merged


def extract_pdf_text(uploaded_file) -> str:
    reader = PdfReader(uploaded_file)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def render_verdict(result: dict):
    st.markdown(f"### {STATUS_COLOR[result['verdict']]} 판정 결과: {result['verdict']}")
    for c in result["checks"]:
        st.markdown(f"{CHECK_COLOR[c['status']]} **{c['description']}** — {c['status']}")
        if c["evidence"]:
            st.caption(f"근거: {c['evidence']}")
        if c["explanation"]:
            st.caption(f"설명: {c['explanation']}")


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
st.title("🏥 방문 예정 환자 프리스크리닝")
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

# ----------------------------------------------------------------------
# 새 환자 추가해서 라이브로 AI 판정 받아보기
# ----------------------------------------------------------------------
st.subheader("➕ 새 환자 추가해서 AI 판정 받아보기")
st.caption("실무에서 실제로 쓰는 방식 그대로 넣을 수 있게 4가지 입력 방법을 지원합니다.")

tab_manual, tab_emr, tab_pdf, tab_excel = st.tabs(
    ["✍️ 직접 입력", "📋 EMR 텍스트 붙여넣기", "📄 판독지 PDF 업로드", "📊 엑셀 일괄 업로드"]
)

# ------------------------------------------------------------------
# 1) 직접 입력
# ------------------------------------------------------------------
with tab_manual:
    new_api_key = st.text_input(
        "Anthropic API Key (이 판정에만 사용되고 저장되지 않습니다)",
        type="password",
        key="new_patient_api_key",
    )

    with st.form("new_patient_form"):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            n_id = st.text_input("환자 ID", value="NEW001")
            n_age = st.number_input("나이", min_value=0, max_value=120, value=65)
            n_sex = st.selectbox("성별", ["남", "여"])
        with col_b:
            n_nyha = st.selectbox("NYHA 기능분류", ["I", "II", "III", "IV"], index=1)
            n_gdmt = st.number_input("GDMT 복용 주수", min_value=0, value=8)
            n_egfr = st.number_input("eGFR", min_value=0, value=60)
        with col_c:
            n_pregnancy = st.selectbox("임신/수유 여부", ["N/A", "임신 아님", "임신", "수유중"])

        n_echo = st.text_area("심초음파(ECHO) 리포트",
                               placeholder="예: 2026-08-10 시행. LVEF 32%, 좌심실 확장 소견, 국소벽운동 이상 없음.")
        n_ekg = st.text_area("심전도(EKG) 소견",
                              placeholder="예: 정상 동리듬(NSR), 특이 부정맥 소견 없음.")
        n_mi = st.text_area("최근 심근경색/뇌졸중 병력", placeholder="예: 없음")
        n_valve = st.text_area("판막질환 소견", placeholder="예: 없음")
        n_crc_note = st.text_area("CRC 메모",
                                   placeholder="예: 복약순응도 양호. 최근 체중 증가 없음.")

        submitted = st.form_submit_button("AI 판정 실행")

    if submitted:
        if not new_api_key:
            st.error("API 키를 먼저 입력해주세요.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = new_api_key
            os.environ.pop("USE_UPSTAGE", None)

            new_patient = {
                "patient_id": n_id, "age": n_age, "sex": n_sex, "nyha_class": n_nyha,
                "gdmt_weeks": n_gdmt, "echo_report": n_echo, "ekg_finding": n_ekg,
                "recent_mi_stroke": n_mi, "valve_disease": n_valve, "egfr": n_egfr,
                "pregnancy": n_pregnancy, "crc_note": n_crc_note,
            }
            with open(engine.CRITERIA_PATH, encoding="utf-8") as f:
                criteria_data = json.load(f)

            with st.spinner("AI가 판정 중..."):
                try:
                    result = engine.screen_patient(new_patient, criteria_data)
                except Exception as e:
                    st.error(f"판정 중 오류가 발생했습니다: {e}")
                    result = None

            if result:
                render_verdict(result)

# ------------------------------------------------------------------
# 2) EMR/PACS에서 복사한 텍스트 붙여넣기 (PHIS 등에서 복사해온 원문 그대로)
# ------------------------------------------------------------------
with tab_emr:
    st.caption("EMR/PACS에서 복사한 텍스트(인적사항, ECHO·EKG 판독문, 병력, CRC 메모 등)를 그대로 붙여넣으면 "
               "AI가 항목별로 알아서 정리한 뒤 판정까지 진행합니다. 원문에 없는 값은 임의로 채우지 않습니다.")

    emr_api_key = st.text_input("Anthropic API Key", type="password", key="emr_api_key")
    emr_raw_text = st.text_area(
        "EMR/PACS 복사 텍스트", height=220,
        placeholder="예)\n68세/남, NYHA III\nECHO(2026-08-10): LVEF 32%, 좌심실 확장 소견\nEKG: 정상 동리듬\nCRC 메모: 지난달 ARNI 증량, 복약순응도 양호",
        key="emr_raw_text",
    )

    if st.button("AI로 정리 후 판정", key="emr_run_btn"):
        if not emr_api_key or not emr_raw_text.strip():
            st.error("API 키와 텍스트를 모두 입력해주세요.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = emr_api_key
            os.environ.pop("USE_UPSTAGE", None)

            with st.spinner("AI가 텍스트에서 환자 정보를 추출하는 중..."):
                extracted = engine.extract_patient_from_text(emr_raw_text)

            st.markdown("**추출된 환자 정보** (원문에 없는 항목은 `null`로 남고, 해당 기준은 '불확실'로 처리됩니다)")
            st.json(extracted)

            with open(engine.CRITERIA_PATH, encoding="utf-8") as f:
                criteria_data = json.load(f)
            with st.spinner("AI가 판정 중..."):
                try:
                    result = engine.screen_patient(extracted, criteria_data)
                except Exception as e:
                    st.error(f"판정 중 오류가 발생했습니다: {e}")
                    result = None
            if result:
                render_verdict(result)

# ------------------------------------------------------------------
# 3) 판독지 PDF 업로드 (ECHO 리포트가 PDF로 저장되는 경우)
# ------------------------------------------------------------------
with tab_pdf:
    st.caption("ECHO 등 판독지를 PDF로 저장해뒀다면 그대로 업로드하세요. 텍스트를 추출해 AI가 항목을 정리하고 판정합니다. "
               "(스캔 이미지형 PDF는 텍스트 추출이 안 될 수 있습니다 - 텍스트 기반 PDF만 지원)")

    pdf_api_key = st.text_input("Anthropic API Key", type="password", key="pdf_api_key")
    pdf_file = st.file_uploader("판독지 PDF 업로드", type=["pdf"], key="pdf_uploader")
    pdf_extra_note = st.text_area("추가로 넣을 정보(선택) - 나이/NYHA/CRC 메모 등 PDF에 없는 내용",
                                   placeholder="예: 74세 여, NYHA II, GDMT 12주째 복용 중", key="pdf_extra_note")

    if st.button("PDF에서 추출 후 판정", key="pdf_run_btn"):
        if not pdf_api_key or not pdf_file:
            st.error("API 키와 PDF 파일을 모두 넣어주세요.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = pdf_api_key
            os.environ.pop("USE_UPSTAGE", None)

            with st.spinner("PDF에서 텍스트 추출 중..."):
                pdf_text = extract_pdf_text(pdf_file)

            if not pdf_text.strip():
                st.error("PDF에서 텍스트를 추출하지 못했습니다. 스캔 이미지형 PDF일 수 있습니다.")
            else:
                with st.expander("추출된 PDF 원문 텍스트 보기"):
                    st.text(pdf_text)

                combined_text = pdf_text + ("\n\n" + pdf_extra_note if pdf_extra_note.strip() else "")
                with st.spinner("AI가 텍스트에서 환자 정보를 추출하는 중..."):
                    extracted = engine.extract_patient_from_text(combined_text)

                st.markdown("**추출된 환자 정보**")
                st.json(extracted)

                with open(engine.CRITERIA_PATH, encoding="utf-8") as f:
                    criteria_data = json.load(f)
                with st.spinner("AI가 판정 중..."):
                    try:
                        result = engine.screen_patient(extracted, criteria_data)
                    except Exception as e:
                        st.error(f"판정 중 오류가 발생했습니다: {e}")
                        result = None
                if result:
                    render_verdict(result)

# ------------------------------------------------------------------
# 4) 엑셀 일괄 업로드 (의무기록팀/PHIS에서 엑셀로 받은 환자 목록)
# ------------------------------------------------------------------
with tab_excel:
    st.caption("PHIS에서 뽑은 **외래예약 환자 리스트**(환자번호·나이·성별 등)와, 의무기록팀에 요청한 "
               "**검사수치 리스트**(환자번호·ECHO·EKG·eGFR 등) — 실제로 따로 나오는 두 엑셀을 각각 업로드하면, "
               "**환자번호를 기준으로 자동 매칭**해서 한 번에 일괄 판정합니다. 둘 다 없어도 괜찮고, 하나만 올려도 동작합니다.")

    et1, et2 = st.columns(2)
    with et1:
        st.download_button(
            "📥 외래예약 리스트 템플릿",
            data=make_appointment_template(),
            file_name="외래예약_환자리스트_템플릿.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with et2:
        st.download_button(
            "📥 검사수치 리스트 템플릿",
            data=make_labs_template(),
            file_name="검사수치_리스트_템플릿.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    excel_api_key = st.text_input("Anthropic API Key", type="password", key="excel_api_key")
    appt_file = st.file_uploader("① 외래예약 환자 리스트 업로드 (.xlsx)", type=["xlsx"], key="appt_uploader")
    labs_file = st.file_uploader("② 검사수치 리스트 업로드 (.xlsx)", type=["xlsx"], key="labs_uploader")

    if st.button("환자번호로 매칭 후 일괄 판정", key="excel_run_btn", disabled=not (appt_file or labs_file)):
        if not excel_api_key:
            st.error("API 키를 먼저 입력해주세요.")
        else:
            os.environ["ANTHROPIC_API_KEY"] = excel_api_key
            os.environ.pop("USE_UPSTAGE", None)

            try:
                appt_rows = read_excel_rows(appt_file, APPT_COLUMN_MAP) if appt_file else []
                labs_rows = read_excel_rows(labs_file, LABS_COLUMN_MAP) if labs_file else []
            except Exception as e:
                st.error(f"엑셀 형식을 읽는 중 문제가 발생했습니다: {e}")
                appt_rows, labs_rows = [], []

            merged = merge_by_patient_id(appt_rows, labs_rows)

            if not merged:
                st.warning("매칭할 환자가 없습니다. 엑셀에 환자번호가 비어있지 않은지 확인해주세요.")
            else:
                appt_ids = {r["patient_id"] for r in appt_rows}
                labs_ids = {r["patient_id"] for r in labs_rows}
                both = appt_ids & labs_ids
                appt_only = appt_ids - labs_ids
                labs_only = labs_ids - appt_ids

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("✅ 양쪽 다 매칭", f"{len(both)}명")
                mc2.metric("📋 외래예약만 있음", f"{len(appt_only)}명")
                mc3.metric("🧪 검사수치만 있음", f"{len(labs_only)}명")
                if appt_only or labs_only:
                    st.caption("한쪽에만 있는 환자는 빠진 정보(예: 검사수치)가 있는 상태로 판정되며, "
                               "해당 기준은 자동으로 '불확실' 처리되어 직접 확인이 필요합니다.")

                with open(engine.CRITERIA_PATH, encoding="utf-8") as f:
                    criteria_data = json.load(f)

                batch_patients = list(merged.values())
                progress = st.progress(0, text="일괄 판정 중...")
                batch_results = []
                for i, p in enumerate(batch_patients):
                    r = engine.screen_patient(p, criteria_data)
                    batch_results.append({**p, "ai_verdict": r["verdict"], "checks": r["checks"]})
                    progress.progress((i + 1) / len(batch_patients),
                                       text=f"{p.get('patient_id')} 처리 중... ({i + 1}/{len(batch_patients)})")
                progress.empty()

                st.success(f"{len(batch_results)}명 판정 완료")
                eb1, eb2, eb3 = st.columns(3)
                eb1.metric("🟢 적격", sum(1 for p in batch_results if p["ai_verdict"] == "적격"))
                eb2.metric("🟡 보류", sum(1 for p in batch_results if p["ai_verdict"] == "보류"))
                eb3.metric("⚪ 부적격", sum(1 for p in batch_results if p["ai_verdict"] == "부적격"))

                for p in batch_results:
                    with st.container(border=True):
                        st.markdown(f"{STATUS_COLOR[p['ai_verdict']]} **{p.get('patient_id')}** — {p['ai_verdict']}")
                        uncertain_or_failed = [c for c in p["checks"] if c["status"] != "충족"]
                        if uncertain_or_failed:
                            st.caption(" · ".join(f"{c['description']} → {c['status']}"
                                                   for c in uncertain_or_failed[:2]))
                        else:
                            st.caption("모든 기준 충족")

st.divider()
st.caption("※ 본 화면은 가상 환자 데이터를 이용한 데모입니다. 실제 환자 데이터는 사용되지 않았습니다.")
