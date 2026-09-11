#!/usr/bin/env python3
"""
작성된 본문을 점검한다.

LLM은 한글 글자수를 세지 못하고, 자기가 쓴 형용사를 스스로 걸러내기 어렵다.
이 스크립트가 그 둘을 대신한다.

점검 항목
  1) 분량      — 공백 포함/제외 글자수, 제한 대비 초과/부족
  2) 완결형    — 상위 메시지(번호 항목)가 3분할 완결형인지
  3) 세부 구조 — 세부 항목에 말머리가 있는지, 2분할로 읽히는지
  4) 금지 표현 — 추상 형용사, 불필요한 접속사, 상투어
  5) 세부 길이 — 세부 항목이 지나치게 긴지 (기본 36자 초과 경고)

사용:
    python lint_text.py 05_본문/배경.md
    python lint_text.py 05_본문/배경.md --limit 2000
    python lint_text.py 05_본문/ --limit 2000        # 폴더 일괄
"""
import argparse
import os
import re
import sys
import unicodedata

# 추상적이라 심사자에게 아무것도 전달하지 못하는 표현
# 최적화·최소화·최대화는 '위상 최적화', '손실 최소화'처럼 기술 용어로도 쓰이므로 제외한다.
# 원자료가 금한 것은 "형용사·추상 표현으로만 채워진" 문장이지 단어 자체가 아니다.
# 양식 표에서 옮긴 값 줄의 구분자. `(현재 수준) [예시] 82% — 전문가 판정 대비 일치율`
VALUE_SEP = " — "

BANNED_ADJ = [
    "극대화", "효율화", "고도화된",
    "최고의", "최상의", "최적의", "혁신적인", "획기적인", "탁월한",
    "우수한", "뛰어난", "다양한", "여러가지", "많은", "폭넓은",
    "적극적으로", "지속적으로", "체계적으로", "효과적으로", "전략적으로",
]
# 개조식 문장 앞에 붙으면 리듬을 깨는 접속사
BANNED_CONJ = [
    "따라서", "그러므로", "그리하여", "이에 따라", "이를 통해",
    "뿐만 아니라", "아울러", "더불어", "또한,", "그러나,",
]
# 흔한 상투어
BANNED_CLICHE = [
    "사료된다", "판단된다", "기대된다", "예상된다", "필요한 실정이다",
    "실정이다", "대두되고 있다", "각광받고 있다", "급부상",
]

# 완결형 판정
#
# 어미만으로는 판정할 수 없다. 교재가 나쁜 예로 든
#   "스마트팜의 종래 온실 제어 시스템의 지능화 결여"
# 도 명사 종결이고, 좋은 예
#   "스마트팜 지능화 결여로 수동 모니터링 의존, 비용 및 리스크 가중"
# 도 명사 종결이다. 실제 차이는 3단 구조({현황}+{주장}+{목적})의 유무다.
# 그래서 '구조 단위를 연결하는 조사·어미'가 몇 개인지로 판정한다.

LINKS = [
    "로 ", "으로 ", "로써", "으로써", "위한 ", "위해 ", "통한 ", "통해 ",
    "기반 ", "따른 ", "따라 ", "대비 ", "하여 ", "함으로", "면서 ",
    "에서 ", "에는 ", "에도 ", "이나 ", "이며", "하며", "및 ", ", ",
]
# 종결로 인정하는 형태 (명사형 종결 포함 — 개조식 문체의 표준)
TERMINAL = re.compile(
    r"(필요|실현|확보|구축|개발|달성|추진|가능|기대|전망|가중|부재|확대|절감|향상|"
    r"단축|강화|마련|전환|창출|해소|극복|대응|확산|정착|보완|도출|증가|감소|지속|"
    r"심화|급증|저하|미흡|한계|요구|우려|적용|도입|실증|검증|제고|개선|"
    r"확인|완료|확정|보유|활용|보호|준수|확립|수립|수행|운영|관리|배치|투입|"
    r"집중|반영|이행|확장|구현|설계|제작|공급|진입|선점|선례|축소|완화|저감|"
    r"제거|방지|차단|필수|목표|계획|체계|기반|"
    r"구성|연동|병행|분할|전담|정의|지정|선정|측정|산출|조율|의무화|도래|"
    r"\d+%|\d+[a-zA-Z]+|\d+건|\d+대|\d+원|\d+개)$"
    r"|(다|함|음|됨|임|필요하다|가능하다)$"
)

NUM_ITEM = re.compile(r"^\s*(\d+)[.)]\s*(.+)$")
SUB_ITEM = re.compile(r"^\s*(?:[-•·]|\*(?!\*)|\d+-\d+\.)\s*(.+)$")

# 06_최종.md의 고정 부분(전략 검토·준비할 입증 자료·심사표 대조)은 본문 문장 규칙 대상이 아니다
STRATEGY_H1 = re.compile(r"^#\s+(전략\s*검토|확인할\s*규정|준비할\s*입증|심사표\s*대조|입증\s*자료)")

# 세부 항목의 말머리: 줄 맨 앞의 (현황) (개발) (타겟 시장) 같은 라벨
LABEL = re.compile(r"^\**\(([^)]{1,12})\)\**\s*|^\**([가-힣A-Za-z][^:：]{0,10})[:：]\s*")

# 2분할 판정
#
# 세부 한 줄은 두 정보 단위를 담되, 조각을 나란히 붙이는 게 아니라
# 조사·연결어미로 이어 하나의 문장으로 만들고 명사형으로 종결해야 한다.
#
#   ⭕ 기존 고정형 자동화의 경직성으로 인한 돌발 변수 대응력 부재
#   ❌ 범용 알고리즘 초고속 회전 대응 · 토크 리플로 응답성 저하   (조각 나열)
#   ❌ 비정형 환경 대응이 어렵다                                 (1분할)
#   ❌ …한계가 있어 수요가 급증하고 있으며 …요구된다              (서술형)
#
# 연결 관계 다섯 가지를 원자료에서 관찰해 정리했다.
CONNECTIVES = {
    "인과": ["로 인한", "으로 인한", "에 따른", "에 따라", "로 인해", "으로 인해"],
    "목적": ["를 위한", "을 위한", "위해 ", "를 통한", "을 통한", "통해 "],
    "수단": ["기반 ", "활용 ", "적용 ", "가능한 ", "방식의 ", "중심의 ", "따른 "],
    "병렬": [" 및 ", "과 ", "와 ", ", "],
    "전환": ["에서 "],
    "관형": ["하는 ", "되는 ", "있는 ", "없는 "],
}
# 위 목록에 없지만 두 단위를 잇는 흔한 조사
LOOSE = ["로 ", "으로 ", "에 ", "의 "]

# 조각 나열 신호
#
# 가운뎃점을 붙여 쓴 '초·중학교', '산업용·서비스용'은 정상적인 열거다.
# 문제가 되는 것은 앞뒤로 공백을 둔 ' · ' — 두 절을 연결 없이 이어붙일 때 나온다.
JAMMED = re.compile(r"[가-힣]\s+[·•]\s+[가-힣]|[가-힣]{2}\s{2,}[가-힣]")

# 세부는 명사형으로 맺는다. 명사형 종결은 종류가 너무 많아 열거할 수 없으므로
# 서술형 종결('~다')만 걸러낸다. '필요', '중요'처럼 '요'로 끝나는 명사는 정상이다.
NARRATIVE = re.compile(
    r"(한다|된다|있다|없다|이다|하다|였다|었다|았다|난다|인다|린다|킨다|진다|"
    r"어렵다|쉽다|높다|낮다|크다|많다|적다|같다|있음|없음)$"
)


def two_part(body):
    """(판정, 사유) — 세부 한 줄이 연결된 2분할인지."""
    b = body.rstrip(".·")
    chars = len(re.sub(r"\s", "", b))
    if chars < 12:
        return False, "1분할로 보임 (12자 미만)"
    if NARRATIVE.search(b):
        return False, "서술형으로 끝남"

    if JAMMED.search(b):               # ' · ' 병치는 연결어가 있어도 조각 나열이다
        return False, "가운뎃점·공백으로 조각을 붙였음"

    padded = b + " "
    rel = [k for k, ws in CONNECTIVES.items() if any(w in padded for w in ws)]
    loose = any(w in padded for w in LOOSE)
    if not rel and not loose:
        return False, "연결어미가 없어 조각 나열로 읽힘"
    return True, ""


def norm_path(path):
    if os.path.exists(path):
        return path
    d = os.path.dirname(path) or "."
    base = unicodedata.normalize("NFC", os.path.basename(path))
    if os.path.isdir(d):
        for f in os.listdir(d):
            if unicodedata.normalize("NFC", f) == base:
                return os.path.join(d, f)
    return path


def count_chars(text):
    """마크다운 마크업과 괄호 주석을 뺀 실질 글자수."""
    t = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    t = re.sub(r"[*_`>|]", "", t)
    t = re.sub(r"\(입증 방안:.*?\)", "", t, flags=re.S)
    with_space = len(t.replace("\n", ""))
    without_space = len(re.sub(r"\s", "", t))
    return with_space, without_space


def strip_marks(s):
    """(#키워드) 접두, 마크다운 강조 제거."""
    s = re.sub(r"^\(#?[^)]{1,20}\)\s*", "", s.strip())
    s = re.sub(r"[*_`]", "", s)
    s = re.sub(r"\s*\(입증 방안:.*$", "", s)
    return s.strip().rstrip(".")


def lint(path, limit=None, sub_max=36):
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    issues = {"분량": [], "금지 표현": [], "완결형": [], "세부 구조": [], "세부 길이": []}

    # 전략 검토 등 고정 부분은 빈 줄로 치환해 줄 번호를 유지한 채 검사에서 제외
    skip = False
    body_lines = []
    for line in lines:
        if line.startswith("# "):
            skip = bool(STRATEGY_H1.match(line))
        body_lines.append("" if skip else line)
    lines = body_lines
    text = "\n".join(lines)

    # 1) 분량
    ws, wos = count_chars(text)
    if limit:
        pct = ws / limit * 100
        verdict = "적정" if 0.85 <= ws / limit <= 1.05 else (
            "초과" if ws > limit else "부족")
        issues["분량"].append(
            f"{ws:,}자 (공백 제외 {wos:,}자) / 제한 {limit:,}자 = {pct:.0f}%  → {verdict}")
    else:
        issues["분량"].append(f"{ws:,}자 (공백 제외 {wos:,}자)")

    # 2) 금지 표현
    for i, line in enumerate(lines, 1):
        for group, words in (("형용사", BANNED_ADJ),
                             ("접속사", BANNED_CONJ),
                             ("상투어", BANNED_CLICHE)):
            for w in words:
                if w in line:
                    snippet = line.strip()[:60]
                    issues["금지 표현"].append(f"L{i} [{group}] '{w}'  — {snippet}")

    # 3) 완결형 / 4) 세부 길이
    for i, line in enumerate(lines, 1):
        m = NUM_ITEM.match(line)
        if m:
            body = strip_marks(m.group(2))
            if not body or "구성단위" in body:      # 템플릿 자리표시자는 건너뜀
                continue
            # 감싸진 상위 메시지: 다음 줄이 들여쓰기된 순수 텍스트면 이어 붙인다
            k = i
            while k < len(lines):
                nx = lines[k]
                if nx.startswith("   ") and nx.strip() and not re.match(r"^\s*([-•*·※(]|\d+[-.)]\s|\d+-\d+\.)", nx):
                    body += " " + nx.strip(); k += 1
                else:
                    break
            units = sum(1 for c in LINKS if c in body + " ")
            blen = len(re.sub(r"\s", "", body))
            # 원자료 예 "지능형 제조 전환 가속화 대응 피지컬 AI 기반 … 기술 필요"는
            # 조사 없이 관형 결합으로 3단을 만든다. 연결어 1개라도 24자 이상이면 인정한다.
            if (units < 2 and blen < 24) or blen < 18:
                issues["완결형"].append(
                    f"L{i} 3단 구조 부족 (연결단위 {units}개, {blen}자) — {body[:60]}\n"
                    f"      → {{현황}}+{{주장}}+{{목적}} 형태로 확장할 것")
            elif not TERMINAL.search(body):
                issues["완결형"].append(
                    f"L{i} 종결이 흐림 — {body[:60]}\n"
                    f"      → '~필요', '~실현', '~30% 저감'처럼 결론이 보이게 맺을 것")
            continue
        if re.match(r"^\s*\d+-\d+\.\s", line):     # 1-1. 소제목 — 말머리 대상 아님
            continue
        s = SUB_ITEM.match(line)
        if s:
            raw = s.group(1).strip()
            head = LABEL.match(raw)
            body = strip_marks(LABEL.sub("", raw, count=1) if head else raw)
            body_len = len(re.sub(r"\s", "", body))

            if "단위 1" in body or "단위 2" in body:
                continue
            if not head:
                issues["세부 구조"].append(
                    f"L{i} 말머리 없음 — {raw[:50]}\n"
                    f"      → '- (현황) …' 처럼 그 줄의 역할을 알리는 라벨을 붙일 것")
            # 양식 표에서 옮긴 값 줄은 `(말머리) 값 — 근거` 형태다.
            # 값 나열이므로 2분할·길이 규칙 대신 값과 근거가 다 있는지만 본다.
            # (01_문장구조.md 6장)
            if VALUE_SEP in body:
                val, _, why_ = body.partition(VALUE_SEP)
                if not val.strip() or not why_.strip():
                    issues["세부 구조"].append(
                        f"L{i} 값 또는 근거가 비었다 — {body[:55]}\n"
                        f"      → '(말머리) 값 — 근거' 형태로 둘 다 채울 것")
                continue

            ok, why = two_part(body)          # 말머리가 없어도 문장 자체는 검사한다
            if not ok:
                issues["세부 구조"].append(
                    f"L{i} {why} — {body[:55]}\n"
                    f"      → 두 단위를 연결어미로 이어 명사형으로 맺을 것 "
                    f"(A로 인한 B / A를 위한 B / A 기반 B / A 및 B / A에서 B로)")

            if body_len > sub_max:
                issues["세부 길이"].append(
                    f"L{i} 세부 {body_len}자 (권장 {sub_max}자 이하) — {body[:50]}…")

    return issues


def report(path, issues):
    print(f"\n{'='*66}\n  {os.path.basename(path)}\n{'='*66}")
    for k in ("분량", "완결형", "세부 구조", "금지 표현", "세부 길이"):
        v = issues[k]
        if k == "분량":
            print(f"\n[{k}]")
            for x in v:
                print(f"  {x}")
            continue
        print(f"\n[{k}] {len(v)}건")
        for x in v[:20]:
            print(f"  {x}")
        if len(v) > 20:
            print(f"  … 외 {len(v)-20}건")
    total = sum(len(issues[k]) for k in ("완결형", "세부 구조", "금지 표현", "세부 길이"))
    print(f"\n→ 지적 사항 총 {total}건")
    return total


def main():
    ap = argparse.ArgumentParser(description="본문 점검")
    ap.add_argument("path", help="파일 또는 폴더")
    ap.add_argument("--limit", type=int, help="분량 제한(글자수, 공백 포함)")
    ap.add_argument("--sub-max", type=int, default=36,
                    help="세부 항목 권장 최대 글자수 (기본 36)")
    args = ap.parse_args()

    p = norm_path(args.path)
    if not os.path.exists(p):
        sys.exit(f"경로를 찾을 수 없습니다: {args.path}")

    targets = []
    if os.path.isdir(p):
        for f in sorted(os.listdir(p)):
            if f.endswith(".md"):
                targets.append(os.path.join(p, f))
    else:
        targets = [p]

    if not targets:
        sys.exit("점검할 .md 파일이 없습니다.")

    grand = 0
    for t in targets:
        grand += report(t, lint(t, args.limit, args.sub_max))

    if len(targets) > 1:
        print(f"\n{'='*66}\n전체 {len(targets)}개 파일, 지적 사항 {grand}건\n{'='*66}")

    print("\n※ 금지 표현은 무조건 삭제 대상이 아니다. 숫자나 구체적 표현으로")
    print("   바꿀 수 있는지 검토하라는 신호로 읽으면 된다.")


if __name__ == "__main__":
    main()
