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
def rule_check(patient: dict, criterion: dict) -> dict:
    field = criterion["field"]
    raw_value = patient[field]

    # 필드 타입에 맞게 형변환
    if field in ("age", "gdmt_weeks", "egfr"):
        value = int(raw_value)
    else:
        value = raw_value

    # criteria.json의 check 문자열을 안전한 로컬 변수로 평가
    local_vars = {field: value, "nyha_class": patient.get("nyha_class"),
                  "pregnancy": patient.get("pregnancy")}
    try:
        passed = eval(criterion["check"], {"__builtins__": {}}, local_vars)
    except Exception as e:
        passed = False

    return {
        "criterion_id": criterion["id"],
        "description": criterion["description"],
        "status": "충족" if passed else "위반",
        "evidence": f"{field} = {raw_value}",
        "explanation": f"규칙 기반 자동 판정 ({criterion['check']})",
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
    user_prompt = USER_PROMPT_TEMPLATE.format(
        criterion_description=criterion["description"],
        field_label=field_label,
        field_text=patient[field],
        crc_note=patient.get("crc_note", ""),
        age=patient.get("age", "?"),
        sex=patient.get("sex", "?"),
        nyha_class=patient.get("nyha_class", "?"),
        gdmt_weeks=patient.get("gdmt_weeks", "?"),
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
        "patient_id": patient["patient_id"],
        "verdict": verdict,
        "checks": checks,
    }


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
