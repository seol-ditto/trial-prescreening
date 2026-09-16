# -*- coding: utf-8 -*-
"""
프리스크리닝 자동화 - 판정 엔진
================================
룰 기반 체크(나이, GDMT 기간, eGFR, 임신 여부처럼 명확한 수치/카테고리 필드)와
LLM 기반 체크(ECHO 리포트, EKG 소견, CRC 자유서술 노트처럼 텍스트 해석이 필요한 필드)를
결합해서 환자별로 "적격 / 보류 / 부적격"을 판정한다.

사용법:
    1. OPENAI/ANTHROPIC/UPSTAGE 중 쓸 LLM API 키를 환경변수로 설정
    2. call_llm() 함수 안의 클라이언트 초기화 부분만 원하는 provider로 교체
       (Upstage Solar는 OpenAI 호환 API라 base_url만 바꾸면 동일한 코드로 동작함 - 대회 파트너사 기술 활용 어필 포인트)
    3. python screening_engine.py 로 실행하면 hf_trial_synthetic_patients.csv를 읽어
       screening_results.csv 로 판정 결과를 출력함
"""

import csv
import json
import os

CRITERIA_PATH = "criteria.json"
PATIENTS_CSV = "hf_trial_synthetic_patients.csv"
OUTPUT_CSV = "screening_results.csv"
OUTPUT_JSON = "screening_results.json"  # Streamlit 화면에서 근거까지 보여주기 위한 상세 결과


# ----------------------------------------------------------------------
# 1. 룰 기반 체크 (숫자/카테고리 필드 - 100% 결정적, 환각 위험 없음)
# ----------------------------------------------------------------------
_MISSING_MARKERS = (None, "", "정보 없음", "N/A", "nan")


def rule_check(patient: dict, criterion: dict) -> dict:
    field = criterion["field"]
    raw_value = patient.get(field)

    try:
        # 엑셀/PDF/EMR 텍스트에서 추출한 데이터는 값이 아예 없을 수 있음 -> 자동판정 불가로 처리
        if field != "pregnancy" and (raw_value in _MISSING_MARKERS or
                                      (isinstance(raw_value, float) and str(raw_value) == "nan")):
            raise ValueError("missing field")

        # 필드 타입에 맞게 형변환
        if field in ("age", "gdmt_weeks", "egfr"):
            value = int(float(raw_value))
        else:
            value = raw_value

        # criteria.json의 check 문자열을 안전한 로컬 변수로 평가
        local_vars = {field: value, "nyha_class": patient.get("nyha_class"),
                      "pregnancy": patient.get("pregnancy")}
        passed = eval(criterion["check"], {"__builtins__": {}}, local_vars)

        return {
            "criterion_id": criterion["id"],
            "description": criterion["description"],
            "status": "충족" if passed else "위반",
            "evidence": f"{field} = {raw_value}",
            "explanation": f"규칙 기반 자동 판정 ({criterion['check']})",
        }
    except Exception:
        return {
            "criterion_id": criterion["id"],
            "description": criterion["description"],
            "status": "불확실",
            "evidence": f"{field} 값 확인 불가",
            "explanation": "필수 정보가 누락되었거나 형식을 인식할 수 없어 자동판정 불가 - 직접 확인 필요",
        }


# ----------------------------------------------------------------------
# 2. LLM 기반 체크 (자유 텍스트 해석이 필요한 필드)
# ----------------------------------------------------------------------
SYSTEM_PROMPT = """당신은 임상시험 프리스크리닝을 돕는 AI 어시스턴트입니다.
주어진 임상시험 기준 하나와, 환자의 진료기록 텍스트(심초음파 리포트/심전도 소견/CRC 메모)를 검토해서
이 환자가 그 기준을 충족하는지 판단하세요.

판단 규칙:
1. 텍스트에 기준을 명확히 위반하는 근거가 있으면 "위반"으로 판단하고, 근거를 그대로 인용하세요.
2. 텍스트에 기준을 충족한다는 근거가 명확하면 "충족"으로 판단하세요.
3. 판단에 필요한 정보가 부족하거나, 자료가 오래됐거나(최신성 의심), 표현이 애매해서 해석이 갈릴 수 있으면
   "불확실"로 판단하고 왜 불확실한지 설명하세요.
4. 텍스트에 없는 내용을 절대 추측하지 마세요. 모르면 "불확실"이라고 답하세요.

아래 JSON 형식으로만 답하세요. 다른 텍스트는 절대 출력하지 마세요.
{
  "status": "충족 | 위반 | 불확실",
  "evidence": "판단에 사용한 원문 근거 인용 (없으면 빈 문자열)",
  "explanation": "판단 이유 한 문장"
}
"""

USER_PROMPT_TEMPLATE = """[임상시험 기준]
{criterion_description}

[환자 기본정보]
나이 {age}세 / {sex} / NYHA {nyha_class} / GDMT 복용 {gdmt_weeks}주째 (처방기록 기준)

[환자 관련 기록 - {field_label}]
{field_text}

[참고: CRC 메모]
{crc_note}
"""

FIELD_LABELS = {
    "echo_report": "심초음파(ECHO) 리포트",
    "ekg_finding": "심전도(EKG) 소견",
    "recent_mi_stroke": "최근 심근경색/뇌졸중 병력",
    "valve_disease": "판막질환 소견",
    "crc_note": "CRC 메모",
}


def call_llm(system_prompt: str, user_prompt: str) -> str:
    """
    실제 LLM API 호출부. USE_UPSTAGE=1 환경변수를 켜면 Upstage Solar로,
    꺼두면(기본값) Anthropic Claude로 호출한다.
    """
    if os.environ.get("USE_UPSTAGE"):
        # Upstage Solar (OpenAI 호환 API) - pip install openai
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ["UPSTAGE_API_KEY"],
            base_url="https://api.upstage.ai/v1/solar",
        )
        response = client.chat.completions.create(
            model="solar-pro",
            max_tokens=500,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    # Anthropic Claude
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def llm_check(patient: dict, criterion: dict) -> dict:
    field = criterion["field"]
    field_label = FIELD_LABELS.get(field, field)
    field_text = patient.get(field)
    if field_text in _MISSING_MARKERS:
        field_text = "(정보 없음 - 원문에서 확인되지 않음)"
    user_prompt = USER_PROMPT_TEMPLATE.format(
        criterion_description=criterion["description"],
        field_label=field_label,
        field_text=field_text,
        crc_note=patient.get("crc_note") or "(정보 없음)",
        age=patient.get("age") or "?",
        sex=patient.get("sex") or "?",
        nyha_class=patient.get("nyha_class") or "?",
        gdmt_weeks=patient.get("gdmt_weeks") or "?",
    )

    raw = call_llm(SYSTEM_PROMPT, user_prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # LLM이 형식을 안 지켰을 때의 안전장치 -> 불확실로 처리
        parsed = {"status": "불확실", "evidence": "", "explanation": "AI 응답 파싱 실패 - 수동 확인 필요"}

    return {
        "criterion_id": criterion["id"],
        "description": criterion["description"],
        "status": parsed.get("status", "불확실"),
        "evidence": parsed.get("evidence", ""),
        "explanation": parsed.get("explanation", ""),
    }


# ----------------------------------------------------------------------
# 3. 결과 종합 (룰 + LLM 결과를 합쳐서 최종 판정)
# ----------------------------------------------------------------------
def combine_verdict(checks: list) -> str:
    statuses = [c["status"] for c in checks]
    if "위반" in statuses:
        return "부적격"
    if "불확실" in statuses:
        return "보류"
    return "적격"


def screen_patient(patient: dict, criteria: dict) -> dict:
    all_criteria = criteria["inclusion_criteria"] + criteria["exclusion_criteria"]
    checks = []
    for c in all_criteria:
        if c["type"] == "rule":
            checks.append(rule_check(patient, c))
        else:
            checks.append(llm_check(patient, c))

    verdict = combine_verdict(checks)
    return {
        "patient_id": patient.get("patient_id") or "UNKNOWN",
        "verdict": verdict,
        "checks": checks,
    }


# ----------------------------------------------------------------------
# 5. 비정형 텍스트(EMR/PACS 복사 붙여넣기, PDF 판독지 추출 텍스트)에서
#    환자 필드를 뽑아내는 전처리 단계 - "복사 → 붙여넣기 → 판정" 워크플로우용
# ----------------------------------------------------------------------
EXTRACTION_SYSTEM_PROMPT = """당신은 CRC가 EMR/PACS에서 복사해온 비정형 텍스트를 정리하는 어시스턴트입니다.
주어진 텍스트에서 아래 항목을 최대한 찾아 JSON으로만 답하세요.

규칙:
1. 텍스트에 없는 항목은 반드시 null로 남기세요. 절대로 추측하거나 지어내지 마세요.
2. recent_mi_stroke / valve_disease 는 명시적 언급이 없으면 null로 두세요 (없다고 단정하지 마세요).
3. 숫자 필드(age, gdmt_weeks, egfr)는 숫자만 추출하세요.

아래 JSON 형식으로만 답하세요. 다른 설명은 절대 출력하지 마세요.
{
  "patient_id": "환자 ID/이니셜 (없으면 null)",
  "age": 나이(정수) 또는 null,
  "sex": "남" 또는 "여" 또는 null,
  "nyha_class": "I|II|III|IV" 또는 null,
  "gdmt_weeks": GDMT 복용 주수(정수) 또는 null,
  "echo_report": "심초음파 판독 관련 원문 내용" 또는 null,
  "ekg_finding": "심전도 소견 관련 원문 내용" 또는 null,
  "recent_mi_stroke": "최근 심근경색/뇌졸중 관련 언급 원문" 또는 null,
  "valve_disease": "판막질환 관련 언급 원문" 또는 null,
  "egfr": eGFR 수치(정수) 또는 null,
  "pregnancy": "임신/수유 관련 언급" 또는 null,
  "crc_note": "그 외 CRC 메모성 내용" 또는 null
}
"""


def extract_patient_from_text(raw_text: str) -> dict:
    """EMR/PACS에서 복사한 비정형 텍스트(또는 PDF에서 추출한 텍스트)를 구조화된 환자 필드로 변환."""
    raw = call_llm(EXTRACTION_SYSTEM_PROMPT, raw_text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    if not data.get("patient_id"):
        data["patient_id"] = "NEW-EMR"
    return data


# ----------------------------------------------------------------------
# 4. 메인 실행부
# ----------------------------------------------------------------------
def main():
    with open(CRITERIA_PATH, encoding="utf-8") as f:
        criteria = json.load(f)

    with open(PATIENTS_CSV, encoding="utf-8-sig") as f:
        patients = list(csv.DictReader(f))

    results = []
    detailed_results = []  # Streamlit용 - 환자 기본정보 + 전체 checks 포함
    for p in patients:
        result = screen_patient(p, criteria)
        failed_or_uncertain = [
            c for c in result["checks"] if c["status"] != "충족"
        ]
        reasoning_summary = " / ".join(
            f"{c['description']}: {c['status']} ({c['explanation']})" for c in failed_or_uncertain
        ) or "모든 기준 충족"

        results.append({
            "patient_id": result["patient_id"],
            "ai_verdict": result["verdict"],
            "expected_verdict": p.get("expected_result", ""),
            "match": result["verdict"] == p.get("expected_result", ""),
            "reasoning_summary": reasoning_summary,
        })
        detailed_results.append({
            **p,  # 원본 환자 필드(나이/성별/echo_report 등) 전부 포함
            "ai_verdict": result["verdict"],
            "checks": result["checks"],
        })
        print(f"{result['patient_id']}: AI={result['verdict']} / 정답={p.get('expected_result')} "
              f"{'✅' if result['verdict'] == p.get('expected_result') else '❌'}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["patient_id", "ai_verdict", "expected_verdict", "match", "reasoning_summary"])
        writer.writeheader()
        writer.writerows(results)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"trial_name": criteria["trial_name"], "patients": detailed_results}, f, ensure_ascii=False, indent=2)

    accuracy = sum(r["match"] for r in results) / len(results)
    print(f"\n정확도: {accuracy:.0%} ({sum(r['match'] for r in results)}/{len(results)})")
    print(f"상세 결과: {OUTPUT_JSON} (Streamlit 화면에서 사용)")


if __name__ == "__main__":
    main()
