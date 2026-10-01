// Human-readable production documents generated from a line and its idea.

const FAMILY_SPEC = {
  strategy: {
    fantasy: "불완전한 정보를 읽고 결정적인 수를 설계하는 지휘관",
    audience: "짧은 세션에서도 생각할 거리를 원하는 전략·퍼즐 플레이어",
    session: "5–8분",
    controls: ["카드 선택", "분석 능력 사용", "재시작"],
    systems: ["매 라운드 변경되는 판정 규칙", "콤보와 집중력 자원", "난이도 상승과 제한 시간"],
    progression: "정답 연속 성공으로 집중력을 얻고 분석 능력을 해금",
    win: "12라운드를 제한 시간과 생명 안에 해결",
    lose: "생명 0 또는 제한 시간 종료",
  },
  action: {
    fantasy: "위험 지역을 돌파하며 자원을 회수하는 생존 파일럿",
    audience: "즉각적인 조작과 짧은 성장 루프를 선호하는 액션 플레이어",
    session: "3–5분",
    controls: ["WASD/방향키 이동", "포인터 이동", "재시작"],
    systems: ["추적 적 회피", "에너지 코어 수집", "보호막과 난이도 상승"],
    progression: "코어 수집으로 점수·속도·보호막이 단계적으로 강화",
    win: "제한 시간 동안 목표 코어를 수집하고 생존",
    lose: "적과 충돌해 내구도 0",
  },
  management: {
    fantasy: "제한된 자원으로 조직을 성장시키는 운영 책임자",
    audience: "계획·효율화·숫자 성장에 만족을 느끼는 경영 플레이어",
    session: "6–10분",
    controls: ["운영 행동 선택", "연구/확장 구매", "다음 날 진행"],
    systems: ["크레딧·에너지·평판 경제", "영구 업그레이드", "12일 목표와 랜덤 이벤트"],
    progression: "연구 배수와 시설 확장으로 일일 자동 수익 증가",
    win: "12일 종료 시 목표 크레딧과 평판 달성",
    lose: "에너지·자금 운용 실패로 목표 미달",
  },
  app: {
    fantasy: "해야 할 일을 빠르고 정확하게 끝내는 사용자",
    audience: "이 주제의 일을 반복해서 처리해야 하는 사람",
    session: "1–5분",
    controls: ["항목 입력", "완료/수정/삭제", "처음으로 되돌리기"],
    systems: ["항목 목록과 상태", "진행률 요약", "빈 화면·오류 안내"],
    progression: "쌓인 기록과 요약으로 다음 작업이 빨라짐",
    win: "사용자가 하려던 일을 막힘 없이 끝냄",
    lose: "입력한 내용이 사라지거나 결과를 믿을 수 없음",
  },
};

export function gddMarkdown(line, idea) {
  const spec = FAMILY_SPEC[line.family] || FAMILY_SPEC.strategy;
  const loop = idea ? idea.loop : ["관찰", "선택", "결과", "성장", "재도전"];
  const list = (items) => items.map((x) => "- " + x).join("\n");
  const feedback = line.feedback.length ? list(line.feedback.map((f) => f.text)) : "- (없음)";
  return [
    "# " + line.title + " — Game Design Document",
    "",
    "- Family: " + line.family,
    "- Type: " + line.gameType,
    "- Target session: " + spec.session,
    "",
    "## High concept",
    "",
    idea ? idea.pitch : line.title,
    "",
    "**Player fantasy:** " + spec.fantasy,
    "",
    "**Audience:** " + spec.audience,
    "",
    "## Core loop",
    "",
    loop.map((x, i) => i + 1 + ". " + x).join("\n"),
    "",
    "## Controls",
    "",
    list(spec.controls),
    "",
    "## Systems",
    "",
    list(spec.systems),
    "",
    "## Progression and outcome",
    "",
    "- Progression: " + spec.progression,
    "- Win: " + spec.win,
    "- Loss: " + spec.lose,
    "",
    "## CEO feedback",
    "",
    feedback,
    "",
  ].join("\n");
}

export function qaMarkdown(line) {
  const rows = [];
  for (const [stageId, stage] of Object.entries(line.stages)) {
    for (const t of stage.tasks) {
      if (t.qa) rows.push("| " + stageId + " | " + t.name + " | " + t.qa + " | " + (t.commit || "-") + " |");
    }
  }
  return [
    "# " + line.title + " — QA Report",
    "",
    "| Stage | Check | Result | Commit |",
    "| --- | --- | --- | --- |",
    ...rows,
    "",
  ].join("\n");
}
