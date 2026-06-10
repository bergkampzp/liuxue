#!/bin/bash
#
# run-pipeline.sh — 留学 AI 数据管线管理脚本
#
# 对齐 power-v2 数据平台的模式：sync → dbt → dashboard
# 依赖：dest-postgres Docker 容器（port 5433）
#
# 用法:
#   ./run-pipeline.sh crawl     # 爬取 GradCafe 数据
#   ./run-pipeline.sh dbt       # 运行 dbt 模型转换
#   ./run-pipeline.sh dashboard # 填充 BI 看板数据
#   ./run-pipeline.sh all       # 一键执行全管线
#   ./run-pipeline.sh status    # 查看数据统计

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-warehouse}"
DB_USER="${DB_USER:-postgres}"
DB_PASS="${DB_PASS:-postgres}"
DB_DSN="host=$DB_HOST port=$DB_PORT dbname=$DB_NAME user=$DB_USER password=$DB_PASS"

# ── Colors ─────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
info() { echo -e "${BLUE}[info]${NC} $*"; }

# ── Ensure DB ──────────────────────────────────────────────────────────
ensure_db() {
    if ! psql "$DB_DSN" -c "SELECT 1" &>/dev/null; then
        echo "❌ 无法连接数据库 $DB_HOST:$DB_PORT/$DB_NAME"
        echo "   请先启动数据平台: docker compose up -d"
        echo "   或设置环境变量: DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASS"
        exit 1
    fi
    log "数据库连接成功: $DB_HOST:$DB_PORT/$DB_NAME"
}

# ── ensure_dbt_profile ─────────────────────────────────────────────────
ensure_dbt_profile() {
    local profile_dir="${HOME}/.dbt"
    local profile_file="${profile_dir}/profiles.yml"

    if [ ! -f "$profile_file" ]; then
        mkdir -p "$profile_dir"
        cat > "$profile_file" << 'EOF'
liuxue:
  outputs:
    local:
      type: postgres
      host: localhost
      port: 5433
      user: postgres
      password: postgres
      dbname: warehouse
      schema: public
      threads: 2
  target: local
EOF
        info "已创建 dbt profile: $profile_file"
    fi
}

# ── crawl ───────────────────────────────────────────────────────────────
crawl() {
    ensure_db
    log "开始爬取 GradCafe 录取数据..."
    cd "$SCRIPT_DIR/crawlers"
    python sync_gradcafe.py "$@"
    log "爬取完成"
}

# ── dbt ─────────────────────────────────────────────────────────────────
run_dbt() {
    ensure_db
    ensure_dbt_profile
    log "运行 dbt 模型转换..."

    cd "$SCRIPT_DIR/dbt_liuxue"

    if ! command -v dbt &>/dev/null; then
        echo "❌ dbt 未安装。请执行: pip install dbt-postgres"
        exit 1
    fi

    dbt debug || { echo "dbt debug 失败"; exit 1; }
    dbt run || { echo "dbt run 失败"; exit 1; }

    log "dbt 完成"
}

# ── dashboard ───────────────────────────────────────────────────────────
dashboard() {
    ensure_db
    log "填充看板数据并输出统计..."

    psql "$DB_DSN" << 'SQL'
-- 录取数据总览
SELECT '=== 录取数据总览 ===' AS info;
SELECT
    COUNT(*) AS total_records,
    COUNT(DISTINCT school) AS schools,
    COUNT(DISTINCT program) AS programs
FROM raw.gradcafe_admissions;

SELECT '=== 各学位录取统计 ===' AS info;
SELECT
    degree,
    COUNT(*) AS cases,
    ROUND(AVG(gpa)::numeric, 2) AS avg_gpa,
    ROUND(AVG(gre_q)::numeric, 1) AS avg_gre_q
FROM raw.gradcafe_admissions
WHERE degree IS NOT NULL AND gpa IS NOT NULL
GROUP BY degree
ORDER BY cases DESC;

SELECT '=== Top 10 申请最热学校 ===' AS info;
SELECT school, COUNT(*) AS cases
FROM raw.gradcafe_admissions
GROUP BY school
ORDER BY cases DESC
LIMIT 10;

SELECT '=== 竞争烈度 (dbt mart层) ===' AS info;
SELECT tier, degree, COUNT(*) AS programs,
    ROUND(AVG(acceptance_rate)::numeric, 3) AS avg_acceptance
FROM mart_school_admission_stats
GROUP BY tier, degree
ORDER BY degree, avg_acceptance;
SQL

    log "看板统计完成"

    echo ""
    log "Metabase 使用提示:"
    echo "  1. 打开 http://localhost:3000"
    echo "  2. 数据源: dest-postgres:5432 (内网) / warehouse"
    echo "  3. 可使用以下表创建问题:"
    echo "     - raw.gradcafe_admissions"
    echo "     - mart_school_admission_stats"
    echo "     - dash_admission_overview"
    echo "     - dash_top_schools"
    echo "     - dash_competition_heatmap"
}

# ── status ──────────────────────────────────────────────────────────────
status() {
    ensure_db
    psql "$DB_DSN" << 'SQL'
SELECT 'raw.gradcafe_admissions' AS table_name, COUNT(*) AS rows
FROM raw.gradcafe_admissions
UNION ALL
SELECT 'stg_gradcafe_admissions', COUNT(*)
FROM stg_gradcafe_admissions
UNION ALL
SELECT 'mart_school_admission_stats', COUNT(*)
FROM mart_school_admission_stats
UNION ALL
SELECT 'dash_admission_overview', COUNT(*)
FROM dash_admission_overview;
SQL
}

# ── all ─────────────────────────────────────────────────────────────────
all() {
    crawl --majors "Computer Science,Data Science" --max-pages 10
    run_dbt
    dashboard
    log "✓ 全管线执行完成"
}

# ── Main ───────────────────────────────────────────────────────────────
case "${1:-}" in
    crawl)
        shift
        crawl "$@"
        ;;
    dbt)
        run_dbt
        ;;
    dashboard)
        dashboard
        ;;
    status)
        status
        ;;
    all)
        all
        ;;
    *)
        echo "用法: $0 {crawl|dbt|dashboard|status|all}"
        echo ""
        echo "  crawl [--majors 'CS,DS' --max-pages 5 --dry-run]"
        echo "      爬取 GradCafe 录取数据"
        echo "  dbt     运行 dbt 模型 (staging→intermediate→features→mart→dashboard)"
        echo "  dashboard  BI 看板统计 + Metabase 提示"
        echo "  status   查看数据统计"
        echo "  all      一键执行完整管线"
        echo ""
        echo "环境变量: DB_HOST DB_PORT DB_NAME DB_USER DB_PASS"
        exit 1
        ;;
esac
