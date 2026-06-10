#!/usr/bin/env python3
"""
bi_dashboard.py — 留学 AI 数据 BI 仪表盘 (Streamlit v2)

用法:
    streamlit run bi_dashboard.py --server.port 8501
"""
import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="留学 AI 数据 BI", layout="wide")

DSN = "host=localhost port=5432 dbname=warehouse user=postgres password=postgres"

@st.cache_data(ttl=60)
def query(sql):
    with psycopg2.connect(DSN) as conn:
        return pd.read_sql(sql, conn)

st.title("🌍 留学 AI 选校 — 数据 BI 仪表盘")
st.caption(f"数据来源: GradCafe + 一亩三分地 + 寄托天下 | 更新时间: 实时 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ── 顶部指标卡片 ──────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
overview = query("""
    SELECT
        (SELECT COUNT(*) FROM raw.gradcafe_admissions) + (SELECT COUNT(*) FROM raw.liuxue_admissions) AS total,
        (SELECT COUNT(DISTINCT school) FROM raw.gradcafe_admissions) AS gc_schools,
        (SELECT COUNT(DISTINCT school) FROM raw.liuxue_admissions) AS liuxue_schools,
        (SELECT COUNT(*) FILTER (WHERE decision ILIKE '%accept%' OR decision ILIKE '%offer%' OR decision = 'AD') FROM raw.gradcafe_admissions) AS gc_accept,
        (SELECT COUNT(*) FILTER (WHERE decision ILIKE '%reject%') FROM raw.gradcafe_admissions) AS gc_reject
""")
rec = overview.iloc[0]
total = rec['total']
gc_schools = rec['gc_schools']
liuxue_schools = rec['liuxue_schools'] or 0
col1.metric("📊 总录取记录", f"{total:,}")
col2.metric("🏫 GradCafe 学校", f"{gc_schools:,}")
col3.metric("🏫 中文站学校", f"{liuxue_schools:,}")
col4.metric("✅ 录取", f"{rec['gc_accept']:,}")
col5.metric("❌ 拒绝", f"{rec['gc_reject']:,}")

# ── GradCafe 数据当前进度 ────────────────────────────────────
gc_count = query("SELECT COUNT(*) AS c FROM raw.gradcafe_admissions").iloc[0]['c']
st.info(f"**GradCafe 当前数据**: {gc_count:,} 条（全量爬取进行中...）")

# ── 侧边栏筛选 ──────────────────────────────────────────────
st.sidebar.header("🔍 筛选条件")
gc_majors = ["All"] + sorted(query("SELECT DISTINCT major_category FROM raw.gradcafe_admissions ORDER BY 1")["major_category"].tolist())
selected_major = st.sidebar.selectbox("GradCafe 专业方向", gc_majors)
gc_degrees = ["All"] + sorted(query("SELECT DISTINCT degree FROM raw.gradcafe_admissions WHERE degree IS NOT NULL ORDER BY 1")["degree"].tolist())
selected_degree = st.sidebar.selectbox("GradCafe 学位", gc_degrees)

where_clauses = []
if selected_major != "All":
    where_clauses.append(f"major_category = '{selected_major}'")
if selected_degree != "All":
    where_clauses.append(f"degree = '{selected_degree}'")
where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

# ═══════════════════════════════════════════════════════════════
# 第一部分：GradCafe 数据分析
# ═══════════════════════════════════════════════════════════════
st.header("📊 GradCafe 录取数据分析")

# ── 第1行: 录取结果 + 学位分布 ──────────────────────────
r1c1, r1c2 = st.columns(2)

with r1c1:
    df_dec = query(f"""
        SELECT CASE
            WHEN decision ILIKE '%accept%' THEN 'Accepted'
            WHEN decision ILIKE '%reject%' THEN 'Rejected'
            WHEN decision ILIKE '%wait%' THEN 'Waitlisted'
            WHEN decision ILIKE '%interview%' THEN 'Interview'
            ELSE 'Other'
        END AS decision_clean,
        COUNT(*) AS count
        FROM raw.gradcafe_admissions
        WHERE {where_sql}
        GROUP BY 1 ORDER BY count DESC
    """)
    fig = px.pie(df_dec, values="count", names="decision_clean",
                 title="录取结果分布", hole=0.4)
    st.plotly_chart(fig, use_container_width=True)

with r1c2:
    df_deg = query(f"""
        SELECT degree, COUNT(*) AS count
        FROM raw.gradcafe_admissions
        WHERE {where_sql} AND degree IS NOT NULL
        GROUP BY degree ORDER BY count DESC
    """)
    fig = px.bar(df_deg, x="degree", y="count", title="学位分布",
                 color="degree", text_auto=True)
    st.plotly_chart(fig, use_container_width=True)

# ── 第2行: Top 学校 + GPA 分布 ────────────────────────────────
r2c1, r2c2 = st.columns(2)

with r2c1:
    df_top = query(f"""
        SELECT school, COUNT(*) AS cases
        FROM raw.gradcafe_admissions
        WHERE {where_sql}
        GROUP BY school ORDER BY cases DESC LIMIT 20
    """)
    fig = px.bar(df_top, x="cases", y="school", title="Top 20 热门学校 (GradCafe)",
                 orientation="h", color="cases", color_continuous_scale="Blues")
    st.plotly_chart(fig, use_container_width=True)

with r2c2:
    df_gpa = query(f"""
        SELECT gpa,
               CASE WHEN decision ILIKE '%accept%' THEN 'Accepted'
                    WHEN decision ILIKE '%reject%' THEN 'Rejected'
                    ELSE 'Other' END AS decision
        FROM raw.gradcafe_admissions
        WHERE {where_sql} AND gpa IS NOT NULL
    """)
    if not df_gpa.empty:
        fig = px.histogram(df_gpa, x="gpa", color="decision", nbins=20,
                           title="GPA 分布（按录取结果）", barmode="overlay",
                           opacity=0.7, color_discrete_sequence=["#00CC96","#EF553B","#AB63FA"])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无 GPA 数据")

# ── 第3行: GPA vs 录取率散点图 + 竞争热力图 ─────────────
st.subheader("🎯 选校匹配分析")

# 学校级别的 GPA-录取率散点图
df_school_stats = query(f"""
    SELECT school, degree,
           ROUND(AVG(gpa)::numeric, 2) AS avg_gpa,
           ROUND(SUM(CASE WHEN decision ILIKE '%accept%' THEN 1 ELSE 0 END)::numeric
                 / NULLIF(COUNT(*), 0), 3) AS acceptance_rate,
           COUNT(*) AS cases
    FROM raw.gradcafe_admissions
    WHERE {where_sql} AND gpa IS NOT NULL
    GROUP BY school, degree
    HAVING COUNT(*) >= 3
    ORDER BY cases DESC
    LIMIT 100
""")

r3c1, r3c2 = st.columns(2)

with r3c1:
    if not df_school_stats.empty:
        fig = px.scatter(df_school_stats, x="avg_gpa", y="acceptance_rate",
                         size="cases", color="degree",
                         hover_name="school",
                         title="GPA vs 录取率（学校维度）",
                         labels={"avg_gpa": "平均 GPA", "acceptance_rate": "录取率",
                                 "degree": "学位", "cases": "样本量"},
                         size_max=30)
        fig.add_hline(y=0.5, line_dash="dash", line_color="gray", opacity=0.3)
        fig.add_vline(x=3.5, line_dash="dash", line_color="gray", opacity=0.3)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无充足数据")

with r3c2:
    # 专业大类录取率对比
    df_major_rate = query(f"""
        SELECT major_category, degree,
               COUNT(*) AS cases,
               ROUND(SUM(CASE WHEN decision ILIKE '%accept%' THEN 1 ELSE 0 END)::numeric
                     / NULLIF(COUNT(*), 0), 3) AS acceptance_rate
        FROM raw.gradcafe_admissions
        WHERE major_category IS NOT NULL AND degree IS NOT NULL
        GROUP BY major_category, degree
        HAVING COUNT(*) >= 3
        ORDER BY acceptance_rate
    """)
    if not df_major_rate.empty:
        fig = px.bar(df_major_rate, x="acceptance_rate", y="major_category",
                     color="degree", barmode="group",
                     title="各专业录取率对比",
                     labels={"acceptance_rate": "录取率", "major_category": "专业方向",
                             "degree": "学位"},
                     orientation="h", text_auto='.0%')
        fig.update_layout(yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无充足数据")

# ── 第4行: GRE 对比 + 年度趋势 ────────────────────────
st.subheader("📈 标化成绩 & 趋势")
r4c1, r4c2 = st.columns(2)

with r4c1:
    df_gre = query(f"""
        SELECT CASE
            WHEN decision ILIKE '%accept%' THEN 'Accepted'
            WHEN decision ILIKE '%reject%' THEN 'Rejected'
            ELSE 'Other'
        END AS decision,
        ROUND(AVG(gre_q)::numeric, 1) AS avg_gre_q,
        ROUND(AVG(gre_v)::numeric, 1) AS avg_gre_v,
        COUNT(*) AS n
        FROM raw.gradcafe_admissions
        WHERE {where_sql} AND gre_q IS NOT NULL
        GROUP BY 1
    """)
    if not df_gre.empty:
        fig = go.Figure(data=[
            go.Bar(name="GRE Q", x=df_gre["decision"], y=df_gre["avg_gre_q"],
                   text=df_gre["avg_gre_q"], textposition='auto'),
            go.Bar(name="GRE V", x=df_gre["decision"], y=df_gre["avg_gre_v"],
                   text=df_gre["avg_gre_v"], textposition='auto'),
        ])
        fig.update_layout(title="录取结果 × 平均 GRE", barmode="group",
                          yaxis_title="GRE 分数")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无 GRE 数据")

with r4c2:
    df_year = query(f"""
        SELECT year, COUNT(*) AS cases
        FROM raw.gradcafe_admissions
        WHERE {where_sql} AND year IS NOT NULL
        GROUP BY year ORDER BY year
    """)
    if not df_year.empty:
        fig = px.line(df_year, x="year", y="cases", title="年度申请量趋势",
                      markers=True, line_shape="spline")
        fig.update_layout(yaxis_title="申请数量")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无年份数据")

# ═══════════════════════════════════════════════════════════════
# 第二阶段：中文站数据（如果存在）
# ═══════════════════════════════════════════════════════════════
liuxue_count = query("SELECT COUNT(*) AS c FROM raw.liuxue_admissions").iloc[0]['c']
if liuxue_count > 0:
    st.header("🇨🇳 中文站录取数据（一亩三分地 + 寄托天下）")

    col_a, col_b = st.columns(2)
    src_dist = query("SELECT source, COUNT(*) AS cnt FROM raw.liuxue_admissions GROUP BY source")
    col_a.dataframe(src_dist, use_container_width=True)

    df_liuxue_dec = query("""
        SELECT decision, COUNT(*) AS cnt
        FROM raw.liuxue_admissions
        GROUP BY decision ORDER BY cnt DESC
    """)
    fig = px.pie(df_liuxue_dec, values="cnt", names="decision", title="中文站录取结果分布")
    col_b.plotly_chart(fig, use_container_width=True)

    # 中文站GPA分布
    df_lgpa = query("""
        SELECT gpa FROM raw.liuxue_admissions WHERE gpa IS NOT NULL
    """)
    if not df_lgpa.empty:
        fig = px.histogram(df_lgpa, x="gpa", nbins=20, title="中文站 GPA 分布")
        st.plotly_chart(fig, use_container_width=True)

# ═══════════════════════════════════════════════════════════════
# 第三阶段：原始数据表
# ═══════════════════════════════════════════════════════════════
st.header("📋 原始录取数据")

tab1, tab2 = st.tabs(["GradCafe", "中文站 (一亩三分地/寄托天下)"])

with tab1:
    with st.expander("展开 GradCafe 数据表", expanded=True):
        df_raw = query(f"""
            SELECT school, program, degree, decision, gpa, gre_q, gre_v, gre_aw,
                   year, major_category, source_url
            FROM raw.gradcafe_admissions
            WHERE {where_sql}
            ORDER BY crawled_at DESC
            LIMIT 500
        """)
        st.dataframe(df_raw, use_container_width=True, height=400)

with tab2:
    if liuxue_count > 0:
        with st.expander("展开中文站数据表", expanded=True):
            df_liuxue = query("""
                SELECT source, school, program, degree, decision, gpa, gre,
                       undergrad_school, undergrad_major, source_url
                FROM raw.liuxue_admissions
                ORDER BY crawled_at DESC
                LIMIT 500
            """)
            st.dataframe(df_liuxue, use_container_width=True, height=400)
    else:
        st.info("中文站数据正在爬取中...")

# ── 页脚 ────────────────────────────────────────────────────
st.divider()
col_a, col_b = st.columns(2)
col_a.caption("数据来源: thegradcafe.com, 1point3acres.com, offer.gter.net")
col_b.caption(f"总计 {total:,} 条记录 | 每 60 秒自动刷新")
