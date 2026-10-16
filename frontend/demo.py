import os

import httpx
import streamlit as st

API = os.environ.get("REPOPILOT_API_URL", "http://127.0.0.1:8000")
st.set_page_config(page_title="RepoPilot", page_icon="🛠️", layout="wide")
st.title("RepoPilot · 智能代码修复")
st.caption("LangGraph + MCP · 本地演示 · 修改保存在独立任务副本")


def api(method, path, **kwargs):
    response = httpx.request(method, API + path, timeout=15, **kwargs)
    response.raise_for_status()
    return response.json()


with st.form("new_task"):
    issue = st.text_area("Bug 描述", "Token 过期时返回 500，预期返回 401；请修复并补充测试。")
    issue_url = st.text_input("可选 GitHub Issue URL（填写后从配置的远端仓库读取需求）")
    repository = st.text_input("本地仓库路径（必须位于后端配置的受控根目录内）", "demo_repository")
    mode = st.selectbox("运行模式", ["multi_full", "multi_no_review", "single"])
    submitted = st.form_submit_button("执行任务", type="primary")

try:
    if submitted:
        result = api(
            "POST",
            "/api/tasks",
            json={
                "issue_description": None if issue_url else issue,
                "github_issue_url": issue_url or None,
                "repository_path": repository,
                "mode": mode,
            },
        )
        st.session_state["task_id"] = result["task_id"]

    task_id = st.text_input("任务 ID（可加载历史任务）", st.session_state.get("task_id", ""))
    st.button("刷新执行进度")
    if task_id:
        state = api("GET", f"/api/tasks/{task_id}")
        st.subheader(f"状态：{state['execution_status']}")
        nodes = [e["node"] for e in state["execution_history"] if e["node"] != "model"]
        st.write(" → ".join(nodes) or "等待调度")
        cols = st.columns(4)
        cols[0].metric("模型调用", state["model_calls"])
        cols[1].metric("输入 / 输出 Token", f"{state['input_tokens']} / {state['output_tokens']}")
        if not state.get("token_usage_complete", True):
            st.warning("部分模型请求没有返回 usage；Token 统计不完整。")
        cols[2].metric("修复重试", state["retry_count"])
        duration = sum(
            e.get("duration_seconds", 0) for e in state["execution_history"] if e["node"] != "model"
        )
        cols[3].metric("节点执行耗时", f"{duration:.2f}s")
        if state["error"]:
            st.error(state["error"])
        diff = api("GET", f"/api/tasks/{task_id}/diff")
        st.subheader("代码 Diff")
        st.code(diff["diff"] or "暂无修改", language="diff")
        st.download_button("下载补丁", diff["diff"], f"{task_id}.patch")
        with st.expander("计划、测试结果与审核", expanded=True):
            st.json(
                {
                    "plan": state["plan"],
                    "tests": state["test_results"],
                    "review": state["review_results"],
                }
            )
        with st.expander("Agent 日志和检索历史"):
            st.json(api("GET", f"/api/tasks/{task_id}/events"))
        if state["execution_status"] == "awaiting_approval":
            left, right = st.columns(2)
            for column, action, label in [
                (left, "approve", "批准当前 Diff"),
                (right, "reject", "拒绝当前 Diff"),
            ]:
                if column.button(label, disabled=not diff["matches_recorded"]):
                    api(
                        "POST",
                        f"/api/tasks/{task_id}/{action}",
                        json={"diff_digest": diff["diff_digest"]},
                    )
                    st.rerun()
        elif state["execution_status"] == "approved":
            st.caption("可选：后端需配置固定 GitHub 仓库与 GITHUB_TOKEN；此操作会创建草稿 PR。")
            if st.button("明确确认：将已批准 Diff 创建为 GitHub 草稿 PR"):
                published = api(
                    "POST", f"/api/tasks/{task_id}/pr", json={"diff_digest": diff["diff_digest"]}
                )
                st.link_button("查看草稿 PR", published["url"])
        elif state["execution_status"] == "blocked":
            if st.button("Docker 就绪后继续测试"):
                api("POST", f"/api/tasks/{task_id}/resume")
                st.rerun()
except (httpx.HTTPError, ValueError) as exc:
    st.error(f"API 请求失败：{exc}")
