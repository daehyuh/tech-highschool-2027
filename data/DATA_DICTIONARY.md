# 특성화고 입시 데이터 사전

## 저장 원칙

- 대학·문서·전형·학과·결과를 분리해 같은 학과의 여러 연도와 여러 원본을 보존한다.
- 대학마다 다른 등급 명칭은 `metrics`에 세로형(long-form)으로 저장한다. 새 지표가 생겨도 열을 추가하지 않고 행을 추가할 수 있다.
- 상담 화면에서 빠르게 비교할 대표값만 `results.representative_grade`에 복사하고, 원래 의미는 `representative_grade_basis`와 `metrics.source_label`로 남긴다.
- 특성화고졸 재직자 전형은 일반 특성화고교졸업자 상담 데이터와 분리한다.
- 공개되지 않은 값은 추정하지 않고 `NULL`로 저장한다.

## 핵심 테이블

| 테이블 | 역할 |
| --- | --- |
| `institutions` | 대학과 캠퍼스 식별 |
| `documents` | PDF·엑셀·공개 HTML 원본, 연도, URL, 해시 |
| `admission_tracks` | 문서 안의 특성화고 전형명과 재직자 여부 |
| `programs` | 모집단위명, 정규화명, 상담용 계열 |
| `results` | 모집·지원·경쟁률·등록·충원·대표등급 |
| `metrics` | 평균, 50%·70% 컷, 최고·최저 등 대학별 세부지표 |
| `raw_tables` | 재검증을 위한 추출 원문 행 |

## 상담용 조회 뷰

- `counseling_results`: 재직자 전형을 제외한 전체 상담용 결과와 원본 URL을 한 번에 조회한다.
- `latest_counseling_results`: 대학·학과별 가장 최근 결과 한 건을 조회한다.

예시:

```sql
SELECT university, program, admission_year, representative_grade, competition_rate, source_url
FROM latest_counseling_results
WHERE field_group = '컴퓨터·AI'
  AND representative_grade BETWEEN 2.5 AND 3.5
ORDER BY representative_grade;
```

## 등급 해석 주의

`grade_70_cut`, `grade_average`, `grade_final_average` 등은 서로 같은 통계가 아니다. 웹의 안정·적정·도전 표시는 대표등급과 학생 등급의 단순 차이만 보여주며 합격 가능성을 의미하지 않는다. 상담 전 원본 URL과 세부 `metrics`를 함께 확인한다.
