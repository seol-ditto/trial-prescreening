# 임상시험 프리스크리닝 자동화 (CRC Prescreening Assistant)

순환기내과 CRC(임상연구코디네이터)가 매일 방문 예정 환자의 EMR을 한 명씩 열람하며 임상시험 참여 가능 여부를 수기로 확인하던 작업을, 룰 기반 + LLM 하이브리드 판정으로 자동화한 프로토타입입니다.

## 문제 상황

CRC는 하루 방문 예정 환자 목록을 두고, 각 환자가 진행 중인 임상시험의 선정/제외기준(연령, 검사 수치, ECHO·EKG 판독문, 병력 등)을 충족하는지 EMR을 뒤져가며 확인합니다. 숙련자도 환자 1명당 3분, 애매한 케이스는 최대 10분까지 걸리는 반복 작업입니다.

## 접근 방식

1. **룰 기반 체크**: 나이·GDMT 복용기간·eGFR·임신 여부처럼 수치/카테고리로 명확히 판정 가능한 기준은 결정적 로직으로 처리 (환각 위험 없음)
2. **LLM 기반 체크**: ECHO 리포트, EKG 소견, CRC 자유서술 메모처럼 텍스트 해석이 필요한 기준은 LLM에게 위반/충족/불확실 3단계로 판단하게 함
3. **3단계 판정**: 하나라도 "위반"이면 **부적격**, 위반 없이 하나라도 "불확실"이면 **보류**(자동 탈락/통과시키지 않고 사람이 재확인), 전부 충족이면 **적격**
4. LLM에게는 "텍스트에 없는 내용은 절대 추측하지 말 것"을 시스템 프롬프트에 명시해 환각으로 인한 오탈락/오통과를 막음
5. 적격 판정 환자는 담당 교수에게 전달할 메모를 자동 생성
6. 데모 화면 하단에서 실무에서 실제 쓰는 방식 그대로 새 환자를 추가해 실시간 AI 판정을 받아볼 수 있음 (4가지 입력 방법 지원)
   - **직접 입력**: 필드별로 타이핑
   - **EMR 텍스트 붙여넣기**: PHIS/EMR에서 복사한 비정형 텍스트를 그대로 붙여넣으면 AI가 항목을 정리 후 판정
   - **판독지 PDF 업로드**: ECHO 등 PDF로 저장된 판독지를 업로드하면 텍스트 추출 후 AI가 정리·판정
   - **엑셀 일괄 업로드**: 의무기록팀/PHIS에서 받은 환자 목록 엑셀(템플릿 제공)을 업로드해 여러 명 한 번에 일괄 판정
7. 필수 정보가 비어있거나 형식이 이상한 값은 자동으로 "불확실"로 처리해 사람이 확인하게 함 (엑셀/PDF/EMR 텍스트처럼 입력이 항상 깔끔하지 않은 경로에서도 안전하게 동작)

## 기술 스택

- Python (룰 엔진 + LLM 연동)
- Anthropic Claude API (기본) / Upstage Solar API (`USE_UPSTAGE=1` 환경변수로 전환 — OpenAI 호환 API라 동일 코드로 동작)
- Streamlit (데모 UI)
- pandas / openpyxl (엑셀 업로드·템플릿), pypdf (PDF 판독지 텍스트 추출)

## 파일 구성

```
├── generate_dataset.py            # 가상 환자 50명 데이터셋 생성 스크립트
├── hf_trial_synthetic_patients.csv # 생성된 가상 환자 데이터 (실제 환자 데이터 아님)
├── criteria.json                  # 임상시험 선정/제외기준 정의 (rule / llm 타입 태깅)
├── screening_engine.py            # 판정 엔진 (룰 체크 + LLM 체크 + 종합 판정)
├── streamlit_app.py               # 데모 화면
├── screening_results.json         # 미리 계산해둔 판정 결과 (데모 시 API 키 없이 바로 조회 가능)
└── screenshots/                   # 데모 화면 스크린샷
```

## 실행 방법

```bash
pip install -r requirements.txt

# 판정 엔진을 직접 돌려보려면 (Anthropic API 키 필요)
export ANTHROPIC_API_KEY=sk-...
python screening_engine.py

# Upstage Solar로 돌리려면
export USE_UPSTAGE=1
export UPSTAGE_API_KEY=up-...
python screening_engine.py

# 데모 화면 실행 (screening_results.json이 있으면 API 키 없이도 바로 조회 가능)
streamlit run streamlit_app.py
```

## 주의사항

- 본 프로젝트는 가상의 임상시험 시나리오와 가상 환자 데이터를 사용한 프로토타입입니다. 실제 환자 데이터는 전혀 사용되지 않았습니다.
- AI 프리스크리닝 결과는 참고용이며, 최종 적격 여부 확인과 동의서 절차는 반드시 담당 CRC/연구자의 확인을 거쳐야 합니다.
