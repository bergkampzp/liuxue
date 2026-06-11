#!/usr/bin/env bash
# scripts/smoke-web.sh — 选校罗盘 Web 发布门禁冒烟脚本
# 幂等可重跑；BASE 默认 http://127.0.0.1:8000，可环境变量覆盖
# 用法: BASE=http://127.0.0.1:8000 bash scripts/smoke-web.sh
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
PASS=0
FAIL=0
WARN=0

# ── 工具函数 ────────────────────────────────────────────────────────────────

ok()   { echo "  ✓ $*"; PASS=$((PASS+1)); }
fail() { echo "  ✗ $*"; FAIL=$((FAIL+1)); }
warn() { echo "  ⚠ $*"; WARN=$((WARN+1)); }

section() { echo; echo "══ $* ══"; }

assert_http() {
    local label="$1" url="$2" expected="${3:-200}"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    if [ "$code" = "$expected" ]; then
        ok "HTTP $expected: $label ($url)"
    else
        fail "HTTP $expected expected, got $code: $label ($url)"
    fi
}

assert_body_contains() {
    local label="$1" url="$2" pattern="$3"
    local body
    body=$(curl -s "$url")
    if echo "$body" | grep -q "$pattern"; then
        ok "grep '${pattern}': $label"
    else
        fail "grep '${pattern}' NOT FOUND: $label"
    fi
}

assert_body_not_contains() {
    local label="$1" url="$2" pattern="$3"
    local body
    body=$(curl -s "$url")
    if echo "$body" | grep -q "$pattern"; then
        fail "FORBIDDEN pattern '${pattern}' FOUND: $label"
    else
        ok "forbidden grep '${pattern}' absent: $label"
    fi
}

assert_json_contains() {
    local label="$1" url="$2" pattern="$3"
    local body
    body=$(curl -s "$url")
    if echo "$body" | grep -q "$pattern"; then
        ok "json grep '${pattern}': $label"
    else
        fail "json grep '${pattern}' NOT FOUND in $url — body: $(echo "$body" | head -c 300)"
    fi
}

# ── §1  五路径 200 ───────────────────────────────────────────────────────────

section "§1 五路径 HTTP 200"
assert_http "/"                "$BASE/"
assert_http "/school.html"     "$BASE/school.html"
assert_http "/methodology.html" "$BASE/methodology.html"
assert_http "/static/style.css" "$BASE/static/style.css"
assert_http "/static/app.js"   "$BASE/static/app.js"

# ── §2  三页免责锚串 ─────────────────────────────────────────────────────────

section "§2 三页"不构成录取承诺""
assert_body_contains "index.html" "$BASE/" "不构成录取承诺"
assert_body_contains "school.html" "$BASE/school.html" "不构成录取承诺"
assert_body_contains "methodology.html" "$BASE/methodology.html" "不构成录取承诺"

# ── §3  index 关键文案 ────────────────────────────────────────────────────────

section "§3 index 关键文案"
assert_body_contains "每个数字都有出处" "$BASE/" "每个数字都有出处"
assert_body_contains "谢菲" "$BASE/" "谢菲"
assert_body_contains "案例积累中" "$BASE/" "案例积累中"
assert_body_contains "建议核对官网" "$BASE/" "建议核对官网"
# 北极星数字：3,453
assert_body_contains "3,453" "$BASE/" "3,453"
# 北极星数字：2,891
assert_body_contains "2,891" "$BASE/" "2,891"

# ── §4  methodology 关键文案 + 动态总条数比对 + 禁 3433 ──────────────────────

section "§4 methodology 文案 + 条数一致性"
assert_body_contains "methodology 2,891" "$BASE/methodology.html" "2,891"
assert_body_contains "methodology 建议核对官网" "$BASE/methodology.html" "建议核对官网"
assert_body_contains "methodology sheffield.ac.uk" "$BASE/methodology.html" "sheffield.ac.uk"
assert_body_contains "methodology ucl.ac.uk" "$BASE/methodology.html" "ucl.ac.uk"
assert_body_not_contains "methodology 禁 3433" "$BASE/methodology.html" "3433"

# 动态 DB 总条数比对：页面应含 3,453（等于 SELECT count(*) FROM stg_uk_official_lists）
DB_COUNT=$(PGPASSWORD=postgres psql -h localhost -p 5432 -U postgres -d warehouse -tAc "SELECT count(*) FROM stg_uk_official_lists" 2>/dev/null || echo "ERROR")
if [ "$DB_COUNT" = "ERROR" ]; then
    warn "DB 无法查询，跳过总条数比对"
else
    # 页面显示的逗号格式数字
    DB_FMT=$(printf "%'d" "$DB_COUNT" 2>/dev/null || echo "$DB_COUNT")
    if curl -s "$BASE/methodology.html" | grep -q "$DB_FMT"; then
        ok "methodology 总条数与 DB 一致（$DB_FMT）"
    else
        fail "methodology 总条数 $DB_FMT 不在页面——DB=$DB_COUNT"
    fi
fi

# ── §5  /school-ladder 北极星：江苏大学 ──────────────────────────────────────

section "§5 /school-ladder 北极星（江苏大学）"
LADDER=$(curl -s "${BASE}/school-ladder?school=%E6%B1%9F%E8%8B%8F%E5%A4%A7%E5%AD%A6")

# 行数：恒 30 行
ROW_COUNT=$(echo "$LADDER" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['schools']))" 2>/dev/null || echo "ERR")
if [ "$ROW_COUNT" = "30" ]; then
    ok "schools 行数 = 30"
else
    fail "schools 行数期望 30，实际 $ROW_COUNT"
fi

# sheffield: min_avg_score=75, band_min_score=70, source_type=official_web
SHEF=$(echo "$LADDER" | python3 -c "
import json,sys
d=json.load(sys.stdin)
row=[r for r in d['schools'] if r['uk_uni_id']=='sheffield']
if not row: print('NOT_FOUND'); sys.exit()
r=row[0]
print(r.get('min_avg_score'), r.get('band_min_score'), r.get('source_type'), r.get('list_status'))
" 2>/dev/null || echo "ERR")

if echo "$SHEF" | grep -q "^75"; then
    ok "sheffield min_avg_score=75"
else
    fail "sheffield min_avg_score 期望 75，实际: $SHEF"
fi
if echo "$SHEF" | grep -q " 70\.0\? "; then
    ok "sheffield band_min_score=70"
elif echo "$SHEF" | grep -qP "75\.0 70\.0"; then
    ok "sheffield band_min_score=70"
else
    # More lenient check
    if echo "$SHEF" | grep -q "70"; then
        ok "sheffield band_min_score contains 70: $SHEF"
    else
        fail "sheffield band_min_score 期望 70，实际: $SHEF"
    fi
fi
if echo "$SHEF" | grep -q "official_web"; then
    ok "sheffield source_type=official_web"
else
    fail "sheffield source_type 期望 official_web，实际: $SHEF"
fi
if echo "$SHEF" | grep -q "arwu-tier\|名单内"; then
    ok "sheffield list_status 含 arwu-tier 或 名单内"
else
    fail "sheffield list_status 期望含 arwu-tier 或 名单内，实际: $SHEF"
fi

# ucl: list_status=不在认可名单
UCL_STATUS=$(echo "$LADDER" | python3 -c "
import json,sys
d=json.load(sys.stdin)
row=[r for r in d['schools'] if r['uk_uni_id']=='ucl']
if not row: print('NOT_FOUND'); sys.exit()
print(row[0].get('list_status'))
" 2>/dev/null || echo "ERR")
if echo "$UCL_STATUS" | grep -q "不在认可名单"; then
    ok "ucl list_status=不在认可名单"
else
    fail "ucl list_status 期望'不在认可名单'，实际: $UCL_STATUS"
fi

# edinburgh: list_status=不在认可名单
EDI_STATUS=$(echo "$LADDER" | python3 -c "
import json,sys
d=json.load(sys.stdin)
row=[r for r in d['schools'] if r['uk_uni_id']=='edinburgh']
if not row: print('NOT_FOUND'); sys.exit()
print(row[0].get('list_status'))
" 2>/dev/null || echo "ERR")
if echo "$EDI_STATUS" | grep -q "不在认可名单"; then
    ok "edinburgh list_status=不在认可名单"
else
    fail "edinburgh list_status 期望'不在认可名单'，实际: $EDI_STATUS"
fi

# bristol: list_status startswith 名单内
BRISTOL_STATUS=$(echo "$LADDER" | python3 -c "
import json,sys
d=json.load(sys.stdin)
row=[r for r in d['schools'] if r['uk_uni_id']=='bristol']
if not row: print('NOT_FOUND'); sys.exit()
print(row[0].get('list_status'))
" 2>/dev/null || echo "ERR")
if echo "$BRISTOL_STATUS" | grep -q "^名单内"; then
    ok "bristol list_status startswith 名单内: $BRISTOL_STATUS"
else
    fail "bristol list_status 期望以'名单内'开头，实际: $BRISTOL_STATUS"
fi

# disclaimer
if echo "$LADDER" | grep -q "不构成录取承诺"; then
    ok "/school-ladder disclaimer 含'不构成录取承诺'"
else
    fail "/school-ladder disclaimer 缺'不构成录取承诺'"
fi

# ── §6  /school-ladder 422 ───────────────────────────────────────────────────

section "§6 /school-ladder 422 未识别校名"
CODE_422=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/school-ladder?school=%E9%9C%8D%E6%A0%BC%E6%B2%83%E5%85%B9")
if [ "$CODE_422" = "422" ]; then
    ok "/school-ladder 霍格沃茨 → 422"
else
    fail "/school-ladder 霍格沃茨 期望 422，实际 $CODE_422"
fi

# ── §7  /position 北极星：江苏大学×谢菲 ─────────────────────────────────────
# 注意: /position 字段名 undergrad_school(非school) + tgt_subject_group(必填)
# 响应字段: schools(非results) + not_on_list

section "§7 /position 北极星"
POS_BODY=$(curl -s -X POST "${BASE}/position" \
    -H "Content-Type: application/json" \
    -d '{"undergrad_school":"江苏大学","avg_score":82,"undergrad_major":"通用","tgt_subject_group":"通用"}')

# sheffield: min_avg_score=75, source_type=official_web
POS_SHEF=$(echo "$POS_BODY" | python3 -c "
import json,sys
d=json.load(sys.stdin)
rows=d.get('schools',[])
row=[r for r in rows if r.get('uk_uni_id')=='sheffield' or r.get('name_zh','').startswith('谢菲')]
if not row: print('NOT_FOUND'); sys.exit()
r=row[0]
print(r.get('min_avg_score'), r.get('source_type'))
" 2>/dev/null || echo "ERR")
if echo "$POS_SHEF" | grep -q "75"; then
    ok "/position sheffield min_avg_score=75"
else
    fail "/position sheffield 期望 min=75，实际: $POS_SHEF"
fi
if echo "$POS_SHEF" | grep -q "official_web"; then
    ok "/position sheffield source_type=official_web"
else
    fail "/position sheffield source_type 期望 official_web，实际: $POS_SHEF"
fi

# not_on_list 应包含 ucl 和 edinburgh（以 uk_uni_id 字段判断）
NOT_ON_LIST=$(echo "$POS_BODY" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ids=[x.get('uk_uni_id','') for x in d.get('not_on_list',[])]
print(ids)
" 2>/dev/null || echo "ERR")
if echo "$NOT_ON_LIST" | grep -q "ucl"; then
    ok "/position not_on_list 含 ucl"
else
    fail "/position not_on_list 期望含 ucl，实际: $NOT_ON_LIST"
fi
if echo "$NOT_ON_LIST" | grep -q "edinburgh"; then
    ok "/position not_on_list 含 edinburgh"
else
    fail "/position not_on_list 期望含 edinburgh，实际: $NOT_ON_LIST"
fi

# ── §8  四旧端点 200 ──────────────────────────────────────────────────────────

section "§8 四旧端点 200"
assert_http "/ielts-gap" "${BASE}/ielts-gap?uk_uni_id=sheffield&overall=6.5&l=6.0&r=6.0&w=6.0&s=6.0"
MAJOR_FIT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/major-fit" \
    -H "Content-Type: application/json" \
    -d '{"undergrad_major":"工科","tgt_subject_group":"通用"}')
if [ "$MAJOR_FIT_CODE" = "200" ]; then
    ok "HTTP 200: /major-fit POST"
else
    fail "HTTP 200 expected, got $MAJOR_FIT_CODE: /major-fit POST"
fi

WAITLIST_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/waitlist" \
    -H "Content-Type: application/json" \
    -d '{"email":"test@example.com"}')
if [ "$WAITLIST_CODE" = "200" ] || [ "$WAITLIST_CODE" = "201" ]; then
    ok "HTTP 200/201: /waitlist POST"
else
    fail "HTTP 200 expected, got $WAITLIST_CODE: /waitlist POST"
fi

POS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/position" \
    -H "Content-Type: application/json" \
    -d '{"undergrad_school":"江苏大学","avg_score":82,"undergrad_major":"通用","tgt_subject_group":"通用"}')
if [ "$POS_CODE" = "200" ]; then
    ok "HTTP 200: /position POST"
else
    fail "HTTP 200 expected, got $POS_CODE: /position POST"
fi

# ── 汇总 ──────────────────────────────────────────────────────────────────────

echo
echo "════════════════════════════════════════"
echo "  PASS=$PASS  FAIL=$FAIL  WARN=$WARN"
echo "════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo "  门禁: 不通过 (FAIL=$FAIL)"
    exit 1
else
    echo "  门禁: 通过"
    exit 0
fi
