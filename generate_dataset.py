# -*- coding: utf-8 -*-
"""
가상 환자 50명 데이터셋 생성 (v2 - 확장판)
==========================================
원래 16명이던 데모용 데이터셋을, 실제 하루 방문 환자 규모에 더 가깝게 50명으로 확장.
각 카테고리(적격 / 부적격-사유별 / 보류-사유별)마다 여러 명을 생성해서
criteria.json 의 5개 LLM 기준 + 4개 룰 기준이 골고루 트리거되도록 설계함.

stub_test.py 의 fake_call_llm() 이 이 파일이 심어둔 마커 문구를 보고 판정을 흉내내므로,
문구를 바꾸면 stub_test.py 도 같이 맞춰야 함.
"""

import csv
import random

random.seed(42)

HEADER = ["patient_id", "age", "sex", "nyha_class", "gdmt_weeks", "echo_report",
          "ekg_finding", "recent_mi_stroke", "valve_disease", "egfr", "pregnancy",
          "crc_note", "expected_result", "reasoning"]

NORMAL_EKG = "정상 동리듬(NSR), 특이 부정맥 소견 없음."
NORMAL_MI = "없음"
NORMAL_VALVE = "없음"

rows = []
pid_counter = 1


def next_id():
    global pid_counter
    pid = f"P{pid_counter:03d}"
    pid_counter += 1
    return pid


def normal_crc_note(gdmt_weeks):
    templates = [
        f"복약순응도 양호. GDMT {gdmt_weeks}주째 안정적으로 유지 중.",
        f"최근 외래에서 특이 호소 없음. GDMT {gdmt_weeks}주째 복용 중이며 처방기록과 일치.",
        f"자녀 동행하에 정기 외래 잘 이행 중. 심부전약 {gdmt_weeks}주째 유지.",
    ]
    return random.choice(templates)


def echo_pass(lvef):
    day = random.randint(1, 28)
    return f"2026-08-{day:02d} 시행. LVEF {lvef}%, 특이 소견 없음."


def echo_high(lvef):
    day = random.randint(1, 28)
    return f"2026-08-{day:02d} 시행. LVEF {lvef}%, 박출률 보존 소견."


def echo_borderline():
    return "2026-08-14 시행. LVEF 40%, 경계성 수치. 판독의 재확인 필요."


def echo_old(lvef):
    return f"2025-11-20 시행(약 9개월 전). LVEF {lvef}%, 좌심실 확장 소견. 최근 6개월 이내 재검사 기록 없음."


def base_patient(age, sex, nyha, gdmt_weeks, echo_report, ekg_finding,
                  recent_mi_stroke, valve_disease, egfr, pregnancy, crc_note,
                  expected_result, reasoning):
    return [next_id(), age, sex, nyha, gdmt_weeks, echo_report, ekg_finding,
            recent_mi_stroke, valve_disease, egfr, pregnancy, crc_note,
            expected_result, reasoning]


# ----------------------------------------------------------------------
# 1. 적격 14명 - 모든 기준 충족
# ----------------------------------------------------------------------
for i in range(14):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, normal_crc_note(gdmt_weeks),
        "적격", f"NYHA {nyha}, LVEF≤40%({lvef}), GDMT {gdmt_weeks}주, 제외기준 해당 없음."
    ))

# ----------------------------------------------------------------------
# 2. 부적격 - 연령 초과(81~95세) 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(81, 95)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, normal_crc_note(gdmt_weeks),
        "부적격", f"연령 {age}세 (선정기준 상한 80세 초과)."
    ))

# ----------------------------------------------------------------------
# 3. 부적격 - 연령 미달(16~18세) 2명
# ----------------------------------------------------------------------
for i in range(2):
    age = random.randint(16, 18)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, normal_crc_note(gdmt_weeks),
        "부적격", f"연령 {age}세 (선정기준 하한 19세 미만)."
    ))

# ----------------------------------------------------------------------
# 4. 부적격 - GDMT 복용기간 4주 미만 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(1, 3)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, f"심부전 치료제 최근 변경({gdmt_weeks}주 전 시작), 아직 목표 용량 도달 전.",
        "부적격", f"GDMT 복용기간 4주 미만({gdmt_weeks}주)."
    ))

# ----------------------------------------------------------------------
# 5. 부적격 - eGFR < 30 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(10, 29)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, "당뇨병성 신증으로 신장내과 병행 진료 중, 최근 크레아티닌 상승 추세.",
        "부적격", f"eGFR {egfr} (기준 30 미만, 신기능저하로 제외기준 해당)."
    ))

# ----------------------------------------------------------------------
# 6. 부적격 - 임신/수유 중 2명
# ----------------------------------------------------------------------
for i in range(2):
    age = random.randint(20, 45)
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = random.choice(["임신", "수유중"])
    rows.append(base_patient(
        age, "여", nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, "최근 산부인과 진료 확인, 담당의와 향후 치료 계획 논의 필요.",
        "부적격", f"{pregnancy} (제외기준 해당)."
    ))

# ----------------------------------------------------------------------
# 7. 부적격 - 최근 3개월 이내 MI/뇌졸중 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    event = random.choice(["최근 3개월 이내 급성심근경색 발생함.", "최근 3개월 이내 뇌졸중 발생함."])
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), "정상 동리듬, 진구성 심근경색 의심 소견.",
        event, NORMAL_VALVE, egfr, pregnancy, "스텐트 시술 후 재활 중, 흉통 재발 없음.",
        "부적격", "최근 3개월 이내 급성심근경색/뇌졸중 병력 (제외기준 해당)."
    ))

# ----------------------------------------------------------------------
# 8. 부적격 - 중등도-중증 판막질환 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI,
        "중등도-중증 승모판 역류 동반.", egfr, pregnancy, "판막수술 상담을 위해 흉부외과 협진 예정.",
        "부적격", "중등도 이상 판막질환 동반 (제외기준 해당)."
    ))

# ----------------------------------------------------------------------
# 9. 부적격 - 조절 안 되는 부정맥(지속성 VT / 조절불량 AFib) 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    if i % 2 == 0:
        ekg = "지속성 심실빈맥(VT) 관찰되어 응급 처치 시행함."
        reason = "지속성 심실빈맥 (제외기준 해당)."
    else:
        hr = random.randint(105, 130)
        ekg = f"지속성 심방세동(AFib), 안정 시 심실박동수 {hr}bpm으로 조절 불량."
        reason = "조절되지 않는 심방세동 (제외기준 해당)."
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), ekg, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, "두근거림 지속 호소, 항응고제 복용 중.",
        "부적격", reason
    ))

# ----------------------------------------------------------------------
# 10. 부적격 - LVEF 40% 초과 (박출률 보존, 기준 미충족) 2명
# ----------------------------------------------------------------------
for i in range(2):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(41, 55)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_high(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, normal_crc_note(gdmt_weeks),
        "부적격", f"LVEF {lvef}% (40% 초과, 박출률 보존으로 선정기준 미충족)."
    ))

# ----------------------------------------------------------------------
# 11. 보류 - 6개월 이내 ECHO 재검사 기록 없음 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_old(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, "다음 외래에서 ECHO 재시행 예정.",
        "보류", "'최근 6개월 이내 ECHO' 요건 충족하는 최신 자료 없음 - 재검사 후 재평가 필요."
    ))

# ----------------------------------------------------------------------
# 12. 보류 - 애매한 AFib 기왕력 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    year = random.choice([2024, 2025])
    ekg = f"심방세동 기왕력 있음({year}년 발생), 현재는 동리듬 유지 중이며 재발 여부 확인 필요."
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), ekg, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, "항부정맥제 복용 중, 부정맥내과 정기 추적 중.",
        "보류", "심방세동 기왕력이 있으나 현재 조절 여부가 애매하여 추가 판단 필요."
    ))

# ----------------------------------------------------------------------
# 13. 보류 - GDMT 진술/처방기록 불일치 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    lvef = random.randint(20, 39)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    crc_note = (f"환자 진술상 심부전약을 '두 달 넘게' 복용 중이라 하나, "
                f"진술과 처방기록이 불일치하여 실제 GDMT 안정 유지기간 확인 필요.")
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_pass(lvef), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, crc_note,
        "보류", "GDMT 유지기간에 대한 환자 진술과 처방기록이 불일치하여 확인 필요."
    ))

# ----------------------------------------------------------------------
# 14. 보류 - 경계선 LVEF(=40%) 3명
# ----------------------------------------------------------------------
for i in range(3):
    age = random.randint(20, 79)
    sex = random.choice(["남", "여"])
    nyha = random.choice(["II", "III"])
    gdmt_weeks = random.randint(4, 24)
    egfr = random.randint(30, 90)
    pregnancy = "N/A" if sex == "남" else "임신 아님"
    rows.append(base_patient(
        age, sex, nyha, gdmt_weeks, echo_borderline(), NORMAL_EKG, NORMAL_MI, NORMAL_VALVE,
        egfr, pregnancy, normal_crc_note(gdmt_weeks),
        "보류", "LVEF 40%로 기준(≤40%) 충족 여부가 판독 오차범위 내에 있어 재확인 필요."
    ))

random.shuffle(rows)
# 셔플 후 ID 재부여 (P001~P050 순서로, 화면에서 보기 좋게)
for idx, row in enumerate(rows, start=1):
    row[0] = f"P{idx:03d}"

with open("/tmp/hf_trial/hf_trial_synthetic_patients.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(HEADER)
    writer.writerows(rows)

print(f"Wrote {len(rows)} patients")
from collections import Counter
print(Counter(r[12] for r in rows))
