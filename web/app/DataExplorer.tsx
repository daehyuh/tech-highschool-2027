"use client";

import { useMemo, useState } from "react";

type Metric = { code: string; label: string; value: number; unit: string | null; percentile: number | null; stage: string | null };
type Result = {
  id: number; source_name: string; canonical_name: string; admission_year: number; track_name: string;
  program_name: string; field_group: string; quota: number | null; applicants: number | null;
  competition_rate: number | null; registrants: number | null; waitlist_rank: number | null;
  representative_grade: number | null; representative_grade_basis: string | null; extraction_confidence: number;
  page_number: number; local_path: string; source_url: string | null; metrics: Metric[];
};
type Dataset = { summary: { result_count: number; institution_count: number; program_count: number; grade_result_count: number }; results: Result[] };
type TargetUniversity = { university: string; cycles: string[]; regions: string[]; status: string; pdf_count: number; source_count: number; result_count: number; program_count: number; grade_result_count: number };
type TargetCoverage = { summary: { target_universities: number; universities_with_pdf: number; universities_with_source: number; universities_with_results: number; universities_with_grade_results: number; statuses: Record<string, number> }; universities: TargetUniversity[] };
type UniversityStat = {
  university: string; regions: string[]; resultCount: number; programCount: number; latestYear: number;
  gradeCount: number; gradeAverage: number | null; gradeBest: number | null; gradeLowest: number | null;
  competitionCount: number; competitionAverage: number | null;
};

const statusLabels: Record<string, string> = {
  grade_available: "등급 조회 가능", results_without_grade: "결과·경쟁률 확인", candidate_not_extracted: "추출 보정 중",
  source_checked_no_result: "공식 공개결과 없음", pdf_without_target_result: "PDF 내 결과 미확인", not_on_nesin: "공식 입학처 수집 필요",
};

const gradeLabels: Record<string, string> = {
  grade_70_cut: "70% 컷", grade_50_cut: "50% 컷", grade_final_average: "최종등록 평균",
  grade_average: "평균등급", grade_final_worst: "최종등록 최저", grade_initial_average: "최초합격 평균",
  grade_final_70_cut: "최종등록 70% 컷", grade_final_75_cut: "최종등록 75% 컷",
  grade_worst: "등록자 최저", grade_75_cut: "75% 컷", grade_all_subject_average: "전과목 평균",
};

type FitTone = "safe" | "fit" | "reach";
type Fit = { text: string; tone: FitTone; gap: number };

function fitLabel(studentGrade: number | null, resultGrade: number | null): Fit | null {
  if (studentGrade === null || resultGrade === null) return null;
  const gap = resultGrade - studentGrade;
  if (gap >= 0.5) return { text: "안정 참고", tone: "safe", gap };
  if (gap >= -0.3) return { text: "적정 참고", tone: "fit", gap };
  return { text: "도전 참고", tone: "reach", gap };
}

function gapText(gap: number) {
  if (Math.abs(gap) < 0.05) return "과거 지표와 비슷함";
  return gap > 0 ? `과거 지표보다 ${gap.toFixed(2)}등급 우위` : `과거 지표보다 ${Math.abs(gap).toFixed(2)}등급 도전`;
}

function resultKey(row: Result) {
  return `${row.canonical_name}|${row.program_name.replace(/[^가-힣a-z0-9]/gi, "").toLowerCase()}`;
}

function valueText(value: number | null, suffix = "") {
  return value === null ? "-" : `${Number.isInteger(value) ? value : value.toFixed(2)}${suffix}`;
}

export function DataExplorer({ data, targetCoverage }: { data: Dataset; targetCoverage: TargetCoverage }) {
  const [gradeInput, setGradeInput] = useState("");
  const [programQuery, setProgramQuery] = useState("");
  const [universityQuery, setUniversityQuery] = useState("");
  const [field, setField] = useState("전체 계열");
  const [region, setRegion] = useState("전체 지역");
  const [year, setYear] = useState("전체 연도");
  const [onlyGrades, setOnlyGrades] = useState(true);
  const [verifiedOnly, setVerifiedOnly] = useState(true);
  const [latestOnly, setLatestOnly] = useState(true);
  const [fitBand, setFitBand] = useState("전체 추천군");
  const [sortBy, setSortBy] = useState("추천순");
  const [visible, setVisible] = useState(40);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [coverageQuery, setCoverageQuery] = useState("");
  const [coverageStatus, setCoverageStatus] = useState("전체 상태");
  const [statsSort, setStatsSort] = useState("등급 평균 순");
  const parsedGrade = gradeInput === "" ? null : Number(gradeInput);
  const gradeError = parsedGrade !== null && (!Number.isFinite(parsedGrade) || parsedGrade < 1 || parsedGrade > 9);
  const studentGrade = gradeError ? null : parsedGrade;

  const fields = useMemo(() => ["전체 계열", ...Array.from(new Set(data.results.map((row) => row.field_group))).sort()], [data.results]);
  const regions = useMemo(() => ["전체 지역", ...Array.from(new Set(targetCoverage.universities.flatMap((row) => row.regions))).sort()], [targetCoverage.universities]);
  const years = useMemo(() => ["전체 연도", ...Array.from(new Set(data.results.map((row) => String(row.admission_year)))).sort().reverse()], [data.results]);
  const resultTargetMap = useMemo(() => {
    const targets = new Map(targetCoverage.universities.map((row) => [row.university, row]));
    const map = new Map<string, TargetUniversity>();
    for (const row of data.results) {
      const target = targets.get(row.canonical_name) ?? targets.get(row.source_name);
      if (!target) continue;
      map.set(row.canonical_name, target);
      map.set(row.source_name, target);
    }
    return map;
  }, [data.results, targetCoverage.universities]);
  const filtered = useMemo(() => {
    const programNeedle = programQuery.trim().toLowerCase();
    const universityNeedle = universityQuery.trim().toLowerCase();
    let rows = data.results
      .filter((row) => !programNeedle || row.program_name.toLowerCase().includes(programNeedle))
      .filter((row) => !universityNeedle || `${row.source_name} ${row.canonical_name}`.toLowerCase().includes(universityNeedle))
      .filter((row) => field === "전체 계열" || row.field_group === field)
      .filter((row) => region === "전체 지역" || (resultTargetMap.get(row.canonical_name) ?? resultTargetMap.get(row.source_name))?.regions.includes(region))
      .filter((row) => year === "전체 연도" || String(row.admission_year) === year)
      .filter((row) => !onlyGrades || row.representative_grade !== null)
      .filter((row) => !verifiedOnly || row.extraction_confidence >= 0.75);

    if (latestOnly) {
      const best = new Map<string, Result>();
      for (const row of rows) {
        const existing = best.get(resultKey(row));
        if (!existing || row.admission_year > existing.admission_year
          || (row.admission_year === existing.admission_year && row.extraction_confidence > existing.extraction_confidence)) {
          best.set(resultKey(row), row);
        }
      }
      rows = [...best.values()];
    }

    if (studentGrade !== null && fitBand !== "전체 추천군") {
      const tone = fitBand === "안정" ? "safe" : fitBand === "적정" ? "fit" : "reach";
      rows = rows.filter((row) => fitLabel(studentGrade, row.representative_grade)?.tone === tone);
    }

    return rows.sort((a, b) => {
      if (sortBy === "등급 높은 순") return (a.representative_grade ?? 99) - (b.representative_grade ?? 99);
      if (sortBy === "등급 여유 순") return (b.representative_grade ?? -1) - (a.representative_grade ?? -1);
      if (sortBy === "최신순") return b.admission_year - a.admission_year || a.source_name.localeCompare(b.source_name, "ko");
      if (studentGrade !== null) {
        const order: Record<FitTone, number> = { fit: 0, safe: 1, reach: 2 };
        const aFit = fitLabel(studentGrade, a.representative_grade);
        const bFit = fitLabel(studentGrade, b.representative_grade);
        const aOrder = aFit ? order[aFit.tone] : 9;
        const bOrder = bFit ? order[bFit.tone] : 9;
        if (aOrder !== bOrder) return aOrder - bOrder;
        const aGap = a.representative_grade === null ? 99 : Math.abs(a.representative_grade - studentGrade);
        const bGap = b.representative_grade === null ? 99 : Math.abs(b.representative_grade - studentGrade);
        if (aGap !== bGap) return aGap - bGap;
      }
      return b.admission_year - a.admission_year || a.source_name.localeCompare(b.source_name, "ko");
    });
  }, [data.results, programQuery, universityQuery, field, region, resultTargetMap, year, onlyGrades, verifiedOnly, latestOnly, fitBand, sortBy, studentGrade]);

  const bandCounts = useMemo(() => {
    const counts = { safe: 0, fit: 0, reach: 0 };
    if (studentGrade === null) return counts;
    const programNeedle = programQuery.trim().toLowerCase();
    const universityNeedle = universityQuery.trim().toLowerCase();
    let rows = data.results
      .filter((row) => !programNeedle || row.program_name.toLowerCase().includes(programNeedle))
      .filter((row) => !universityNeedle || `${row.source_name} ${row.canonical_name}`.toLowerCase().includes(universityNeedle))
      .filter((row) => field === "전체 계열" || row.field_group === field)
      .filter((row) => region === "전체 지역" || (resultTargetMap.get(row.canonical_name) ?? resultTargetMap.get(row.source_name))?.regions.includes(region))
      .filter((row) => year === "전체 연도" || String(row.admission_year) === year)
      .filter((row) => row.representative_grade !== null)
      .filter((row) => !verifiedOnly || row.extraction_confidence >= 0.75);
    if (latestOnly) {
      const best = new Map<string, Result>();
      for (const row of rows) {
        const existing = best.get(resultKey(row));
        if (!existing || row.admission_year > existing.admission_year
          || (row.admission_year === existing.admission_year && row.extraction_confidence > existing.extraction_confidence)) best.set(resultKey(row), row);
      }
      rows = [...best.values()];
    }
    for (const row of rows) {
      const fit = fitLabel(studentGrade, row.representative_grade);
      if (fit) counts[fit.tone] += 1;
    }
    return counts;
  }, [data.results, programQuery, universityQuery, field, region, resultTargetMap, year, verifiedOnly, latestOnly, studentGrade]);
  const universityStats = useMemo(() => {
    const groups = new Map<string, {
      university: string; regions: string[]; rows: number; programs: Set<string>; latestYear: number;
      grades: number[]; competitions: number[];
    }>();
    for (const row of filtered) {
      const target = resultTargetMap.get(row.canonical_name) ?? resultTargetMap.get(row.source_name);
      const university = target?.university ?? row.canonical_name;
      const current = groups.get(university) ?? {
        university, regions: target?.regions ?? [], rows: 0, programs: new Set<string>(), latestYear: row.admission_year,
        grades: [], competitions: [],
      };
      current.rows += 1;
      current.programs.add(row.program_name);
      current.latestYear = Math.max(current.latestYear, row.admission_year);
      if (row.representative_grade !== null) current.grades.push(row.representative_grade);
      if (row.competition_rate !== null) current.competitions.push(row.competition_rate);
      groups.set(university, current);
    }
    const average = (values: number[]) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    const stats: UniversityStat[] = [...groups.values()].map((group) => ({
      university: group.university,
      regions: group.regions,
      resultCount: group.rows,
      programCount: group.programs.size,
      latestYear: group.latestYear,
      gradeCount: group.grades.length,
      gradeAverage: average(group.grades),
      gradeBest: group.grades.length ? Math.min(...group.grades) : null,
      gradeLowest: group.grades.length ? Math.max(...group.grades) : null,
      competitionCount: group.competitions.length,
      competitionAverage: average(group.competitions),
    }));
    return stats.sort((a, b) => {
      if (statsSort === "결과 많은 순") return b.resultCount - a.resultCount || a.university.localeCompare(b.university, "ko");
      if (statsSort === "경쟁률 높은 순") return (b.competitionAverage ?? -1) - (a.competitionAverage ?? -1) || a.university.localeCompare(b.university, "ko");
      if (statsSort === "대학명 순") return a.university.localeCompare(b.university, "ko");
      return (a.gradeAverage ?? 99) - (b.gradeAverage ?? 99) || a.university.localeCompare(b.university, "ko");
    });
  }, [filtered, resultTargetMap, statsSort]);
  const filteredCoverage = useMemo(() => targetCoverage.universities.filter((row) =>
    (!coverageQuery.trim() || `${row.university} ${row.regions.join(" ")}`.toLowerCase().includes(coverageQuery.trim().toLowerCase()))
    && (coverageStatus === "전체 상태" || row.status === coverageStatus)
  ), [targetCoverage.universities, coverageQuery, coverageStatus]);

  const reset = () => {
    setGradeInput(""); setProgramQuery(""); setUniversityQuery(""); setField("전체 계열"); setRegion("전체 지역"); setYear("전체 연도");
    setOnlyGrades(true); setVerifiedOnly(true); setLatestOnly(true); setFitBand("전체 추천군"); setSortBy("추천순");
    setVisible(40); setExpanded(null);
  };

  return <main>
    <header className="topbar"><a className="brand" href="#top" aria-label="특성화고 입시 데이터랩 홈"><span className="brand-mark">특</span><span>특성화고 입시 데이터랩</span></a><nav><a href="#search">입결 검색</a><a href="#statistics">대학 통계</a><a href="#coverage">수집 현황</a><a href="#guide">데이터 안내</a></nav></header>

    <section className="hero" id="top">
      <div className="hero-copy"><p className="eyebrow">VOCATIONAL ADMISSION INTELLIGENCE</p><h1>흩어진 대학 입결을<br/><span>상담 가능한 데이터</span>로.</h1><p className="hero-description">특성화고 전형의 학과별 모집·경쟁률·등급 지표를 한곳에서 비교하세요. 원본 PDF의 페이지와 대학별 지표명까지 함께 보존했습니다.</p></div>
      <div className="hero-stats" aria-label="데이터 현황"><div><strong>{data.summary.result_count.toLocaleString()}</strong><span>구조화 행</span></div><div><strong>{targetCoverage.summary.universities_with_results}/{targetCoverage.summary.target_universities}</strong><span>조회 가능 / 모집 대상</span></div><div><strong>{data.summary.program_count}</strong><span>학과 데이터</span></div><div><strong>{data.summary.grade_result_count}</strong><span>등급 비교 가능</span></div></div>
      <p className="coverage-note">82개 대학 공식 근거 대조 완료 · 학과별 결과 {targetCoverage.summary.universities_with_results}개 대학 · 등급 공개 {targetCoverage.summary.universities_with_grade_results}개 대학</p>
    </section>

    <section className="workspace" id="search">
      <aside className="filters">
        <div className="filter-heading"><div><p className="section-kicker">FILTERS</p><h2>상담 조건</h2></div><button className="text-button" onClick={reset}>초기화</button></div>
        <label><span>학생 내신등급</span><input type="number" min="1" max="9" step="0.01" value={gradeInput} onChange={(event) => { setGradeInput(event.target.value); setFitBand("전체 추천군"); setVisible(40); }} placeholder="예: 2.75" aria-invalid={gradeError} aria-describedby="grade-help" /><small id="grade-help" className={gradeError ? "input-help error" : "input-help"}>{gradeError ? "1.00~9.00 사이 등급을 입력하세요." : "숫자가 낮을수록 우수한 내신등급입니다."}</small></label>
        <label><span>희망 학과</span><input value={programQuery} onChange={(event) => setProgramQuery(event.target.value)} placeholder="컴퓨터, 경영, 간호…" /></label>
        <label><span>대학교</span><input value={universityQuery} onChange={(event) => setUniversityQuery(event.target.value)} placeholder="대학명 검색" /></label>
        <div className="select-grid"><label><span>계열</span><select value={field} onChange={(event) => { setField(event.target.value); setVisible(40); }}>{fields.map((item) => <option key={item}>{item}</option>)}</select></label><label><span>지역</span><select value={region} onChange={(event) => { setRegion(event.target.value); setVisible(40); }}>{regions.map((item) => <option key={item}>{item}</option>)}</select></label></div>
        <label><span>입시연도</span><select value={year} onChange={(event) => { setYear(event.target.value); setVisible(40); }}>{years.map((item) => <option key={item}>{item}</option>)}</select></label>
        <div className="select-grid"><label><span>추천군</span><select value={fitBand} disabled={studentGrade === null} onChange={(event) => { setFitBand(event.target.value); setVisible(40); }}><option>전체 추천군</option><option>안정</option><option>적정</option><option>도전</option></select></label><label><span>정렬</span><select value={sortBy} onChange={(event) => setSortBy(event.target.value)}><option>추천순</option><option>최신순</option><option>등급 높은 순</option><option>등급 여유 순</option></select></label></div>
        <label className="check"><input type="checkbox" checked={onlyGrades} onChange={(event) => setOnlyGrades(event.target.checked)} /><span>등급 데이터가 있는 결과만</span></label>
        <label className="check"><input type="checkbox" checked={verifiedOnly} onChange={(event) => setVerifiedOnly(event.target.checked)} /><span>신뢰도 높은 자동 추출만</span></label>
        <label className="check"><input type="checkbox" checked={latestOnly} onChange={(event) => setLatestOnly(event.target.checked)} /><span>대학·학과별 최신 결과만</span></label>
        <div className="fit-legend"><span className="dot safe"/>학생 성적이 지표보다 충분히 우수 <span className="dot fit"/>유사 <span className="dot reach"/>도전</div>
      </aside>

      <section className="results-panel">
        {studentGrade !== null ? <div className="counsel-summary">
          <div><p className="section-kicker">COUNSELING SNAPSHOT</p><h2>{studentGrade.toFixed(2)}등급 기준 추천 분포</h2><p>{programQuery.trim() ? `희망 학과 “${programQuery.trim()}”` : field !== "전체 계열" ? `${field} 계열` : "전체 계열"} · {latestOnly ? "대학·학과별 최신 공개결과" : "전체 연도 공개결과"} 기준</p></div>
          <div className="band-buttons" aria-label="추천군별 결과 수">
            <button className={fitBand === "안정" ? "active safe" : "safe"} onClick={() => setFitBand(fitBand === "안정" ? "전체 추천군" : "안정")}><span>안정 참고</span><strong>{bandCounts.safe}</strong><small>과거 지표보다 0.50↑</small></button>
            <button className={fitBand === "적정" ? "active fit" : "fit"} onClick={() => setFitBand(fitBand === "적정" ? "전체 추천군" : "적정")}><span>적정 참고</span><strong>{bandCounts.fit}</strong><small>-0.30~+0.49</small></button>
            <button className={fitBand === "도전" ? "active reach" : "reach"} onClick={() => setFitBand(fitBand === "도전" ? "전체 추천군" : "도전")}><span>도전 참고</span><strong>{bandCounts.reach}</strong><small>과거 지표보다 0.30↓</small></button>
          </div>
          <p className="summary-disclaimer">추천군은 합격 확률이 아니라 대학이 공개한 서로 다른 기준의 등급지표와 학생 등급의 단순 차이입니다. 실제 상담에서는 전형방법·교과반영·모집인원도 함께 확인하세요.</p>
        </div> : <div className="recommendation-prompt"><strong>학생 등급을 입력하면 대학·학과별 최신 결과를 적정·안정·도전 순으로 추천합니다.</strong><span>희망 학과 또는 계열을 함께 선택하면 상담 후보를 더 빠르게 좁힐 수 있습니다.</span></div>}
        <div className="results-heading"><div><p className="section-kicker">RESULTS</p><h2>{filtered.length.toLocaleString()}개의 비교 결과</h2></div><p>{studentGrade !== null ? `${studentGrade.toFixed(2)}등급 추천순 · ${fitBand}` : "최신 연도·대학순"}</p></div>
        {filtered.length === 0 ? <div className="empty"><strong>조건에 맞는 결과가 없습니다.</strong><span>등급 데이터 또는 검증 필터를 해제해 보세요.</span></div> : <div className="result-list">
          {filtered.slice(0, visible).map((row) => {
            const fit = fitLabel(studentGrade, row.representative_grade); const open = expanded === row.id;
            return <article className="result-card" key={row.id}>
              <button className="card-main" onClick={() => setExpanded(open ? null : row.id)} aria-expanded={open}>
                <div className="university-cell"><span className="year-chip">{row.admission_year}</span><strong>{row.source_name}</strong><small>{row.canonical_name}</small></div>
                <div className="program-cell"><span>{row.field_group}</span><strong>{row.program_name}</strong><small>{row.track_name}</small></div>
                <div className="metric-cell"><span>대표 등급</span><strong>{valueText(row.representative_grade)}</strong><small>{row.representative_grade_basis ? gradeLabels[row.representative_grade_basis] ?? row.representative_grade_basis : "미공개"}</small></div>
                <div className="metric-cell"><span>경쟁률</span><strong>{valueText(row.competition_rate, row.competition_rate === null ? "" : ":1")}</strong><small>모집 {valueText(row.quota, "명")}</small></div>
                <div className="fit-cell">{fit ? <span className={`fit-badge ${fit.tone}`} title={gapText(fit.gap)}>{fit.text}<small>{gapText(fit.gap)}</small></span> : <span className="fit-badge muted">성적 입력 대기</span>}<span className="chevron">{open ? "−" : "+"}</span></div>
              </button>
              {open && <div className="card-detail"><div><h3>대학이 발표한 세부 지표</h3><div className="metric-grid">{row.metrics.filter((metric) => metric.code !== "raw_metric").slice(0, 12).map((metric, index) => <div key={`${metric.code}-${index}`}><span>{metric.label}</span><strong>{valueText(metric.value)}</strong></div>)}</div></div><div className="source-box"><span>원본 근거</span><strong>{row.local_path.toLowerCase().endsWith(".pdf") ? `PDF ${row.page_number}쪽` : row.local_path.toLowerCase().endsWith(".xlsx") ? "대학 공식 엑셀" : "대입정보포털 공개표"}</strong><small>{row.local_path.split(/[\\/]/).pop()}</small><p>자동 추출 신뢰도 {Math.round(row.extraction_confidence * 100)}%</p>{row.source_url && <a href={row.source_url} target="_blank" rel="noreferrer">공식 원문 열기 ↗</a>}</div></div>}
            </article>;
          })}
        </div>}
        {visible < filtered.length && <button className="load-more" onClick={() => setVisible((count) => count + 40)}>40개 더 보기</button>}
      </section>
    </section>

    <section className="statistics-section" id="statistics">
      <div className="statistics-heading">
        <div><p className="section-kicker">UNIVERSITY STATISTICS</p><h2>현재 상담 조건의 대학별 통계</h2><p>위 입결 검색 조건과 연동된 결과를 대학 단위로 묶었습니다. 서로 다른 대학의 대표등급 기준을 단순 평균한 참고 통계입니다.</p></div>
        <div className="statistics-control"><label htmlFor="statistics-sort">정렬</label><select id="statistics-sort" value={statsSort} onChange={(event) => setStatsSort(event.target.value)}><option>등급 평균 순</option><option>결과 많은 순</option><option>경쟁률 높은 순</option><option>대학명 순</option></select><strong>{universityStats.length}개 대학</strong></div>
      </div>
      {universityStats.length === 0 ? <div className="statistics-empty">현재 검색 조건으로 계산할 대학 통계가 없습니다.</div> : <div className="statistics-grid">
        {universityStats.map((stat) => <article className="statistics-card" key={stat.university}>
          <div className="statistics-card-title"><div><span>{stat.regions.join(" · ") || "지역 미표기"}</span><h3>{stat.university}</h3></div><em>{stat.latestYear}</em></div>
          <div className="statistics-primary"><span>대표등급 단순 평균</span><strong>{valueText(stat.gradeAverage)}</strong><small>{stat.gradeCount ? `${valueText(stat.gradeBest)} ~ ${valueText(stat.gradeLowest)} · ${stat.gradeCount}건` : "등급 미공개"}</small></div>
          <dl><div><dt>평균 경쟁률</dt><dd>{valueText(stat.competitionAverage, stat.competitionAverage === null ? "" : ":1")}</dd></div><div><dt>모집단위</dt><dd>{stat.programCount}개</dd></div><div><dt>비교 결과</dt><dd>{stat.resultCount}건</dd></div></dl>
          <button onClick={() => { setUniversityQuery(stat.university); setVisible(40); document.getElementById("search")?.scrollIntoView({ behavior: "smooth" }); }}>이 대학 결과 보기</button>
        </article>)}
      </div>}
    </section>

    <section className="coverage-section" id="coverage">
      <div className="coverage-heading"><div><p className="section-kicker">COLLECTION STATUS</p><h2>모집 대상 82개 대학 수집 현황</h2><p>원본 모집대학 엑셀을 기준으로 대학 공식자료와 대입정보포털 공개표준안을 함께 대조합니다.</p></div><div className="coverage-summary"><span>공식 근거 <strong>{targetCoverage.summary.universities_with_source}</strong></span><span>결과 <strong>{targetCoverage.summary.universities_with_results}</strong></span><span>등급 <strong>{targetCoverage.summary.universities_with_grade_results}</strong></span></div></div>
      <div className="coverage-controls"><input value={coverageQuery} onChange={(event) => setCoverageQuery(event.target.value)} placeholder="대학 또는 지역 검색" aria-label="수집 현황 대학 검색"/><select value={coverageStatus} onChange={(event) => setCoverageStatus(event.target.value)} aria-label="수집 상태 필터"><option>전체 상태</option>{Object.keys(statusLabels).map((status) => <option key={status} value={status}>{statusLabels[status]} ({targetCoverage.summary.statuses[status] ?? 0})</option>)}</select><span>{filteredCoverage.length}개 대학</span></div>
      <div className="coverage-table" role="table" aria-label="대학별 데이터 수집 현황"><div className="coverage-row coverage-header" role="row"><span>대학</span><span>모집</span><span>근거</span><span>학과 결과</span><span>등급 결과</span><span>상태</span></div>{filteredCoverage.map((row) => <div className="coverage-row" role="row" key={row.university}><strong>{row.university}<small>{row.regions.join(" · ") || "지역 미표기"}</small></strong><span>{row.cycles.map((cycle) => cycle.replace("모집", "")).join(" · ")}</span><span>{row.source_count}</span><span>{row.program_count}</span><span>{row.grade_result_count}</span><span><em className={`status-pill ${row.status}`}>{statusLabels[row.status] ?? row.status}</em></span></div>)}</div>
    </section>

    <section className="guide" id="guide"><div><p className="section-kicker">HOW TO READ</p><h2>등급 하나로 합격을 단정하지 않습니다.</h2></div><div className="guide-grid"><article><span>01</span><h3>지표 기준 보존</h3><p>평균, 50% 컷, 70% 컷, 최초합격·최종등록 등 대학이 발표한 기준을 구분해 저장합니다.</p></article><article><span>02</span><h3>원본 역추적</h3><p>PDF, 대학 공식 엑셀, 대입정보포털 공개표까지 출처를 연결해 상담 전 재검수가 가능합니다.</p></article><article><span>03</span><h3>미공개와 누락 구분</h3><p>모집 대상 {targetCoverage.summary.target_universities}개 전체가 등급을 공개한 것은 아닙니다. 공식 공개결과 없음과 추출 누락을 구분해 수집 범위를 과장하지 않습니다.</p></article><article><span>04</span><h3>상담 보조용</h3><p>안정·적정·도전 표시는 단순 등급 차이 비교이며 실제 지원 가능성을 보장하지 않습니다.</p></article></div></section>
    <footer><strong>특성화고 입시 데이터랩</strong><p>대학 발표 자료 기반 · 상담용 내부 데이터 플랫폼</p></footer>
  </main>;
}
