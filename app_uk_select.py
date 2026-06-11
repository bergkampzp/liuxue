# app_uk_select.py — MVP-1 对外前端。运行: streamlit run app_uk_select.py
import requests
import streamlit as st

API = "http://localhost:8800"
BADGE = {"official_web": "🔵 官方公布", "official_pdf": "🔵 官方公布",
         "aggregator": "🟡 参考线·待核", "case_inferred": "⚪ 案例估计"}

st.set_page_config(page_title="英国选校定位", layout="wide")
st.title("英国选校定位 — 每个数字都有出处")

with st.form("profile"):
    c1, c2, c3 = st.columns(3)
    school = c1.text_input("本科院校", placeholder="如：江苏大学")
    score = c2.number_input("均分(百分制)", 50.0, 100.0, 82.0, 0.5)
    major = c3.text_input("本科专业", placeholder="如：软件工程")
    c4, c5 = st.columns(2)
    group = c4.selectbox("目标方向", ["通用", "商科金融", "CS与数据", "工科", "社科"])
    ielts = c5.number_input("雅思总分(可选,0=未考)", 0.0, 9.0, 6.5, 0.5)
    submitted = st.form_submit_button("看我能上哪些学校", use_container_width=True)

if submitted:
    r = requests.post(f"{API}/position", json={
        "undergrad_school": school, "avg_score": score, "undergrad_major": major,
        "tgt_subject_group": group, "ielts_overall": ielts or None}, timeout=30)
    if r.status_code == 422:
        detail = r.json().get("detail", {})
        st.error(detail.get("msg", "输入有误") if isinstance(detail, dict) else str(detail))
    else:
        data = r.json()
        st.caption(f"识别院校：{data['cn_university']['name_zh']}"
                   f"（{data['cn_university']['tier_label']}）")
        if data.get("major_fit"):
            mf = data["major_fit"]
            st.info(f"专业判定：{mf['src_major_category']} → {mf['fit_level']}"
                    + (f"（需先修：{mf['required_prereqs']}）" if mf.get("required_prereqs") else ""))
        for bucket, emoji in [("冲", "🚀"), ("匹", "🎯"), ("保", "🛡️"), ("不建议", "⛔")]:
            rows = [s for s in data["schools"] if s["tier"] == bucket]
            if not rows:
                continue
            st.subheader(f"{emoji} {bucket} ({len(rows)})")
            for s in rows:
                with st.container(border=True):
                    st.markdown(f"**{s['name_zh']}** (QS {s['qs_rank']})　"
                                f"{BADGE.get(s['source_type'], s['source_type'])}")
                    st.write(s["explanation"])
                    st.markdown(f"[数据出处]({s['source_url']})")
        st.divider()
        st.info(data.get("waitlist_hint", ""))
        email = st.text_input("留下邮箱，缺失学校上线第一时间通知你")
        if st.button("登记") and email:
            requests.post(f"{API}/waitlist", json={"email": email}, timeout=10)
            st.success("已登记！")
        st.caption("免责声明：录取结果由学校最终决定，本平台数据用于规划参考。")
