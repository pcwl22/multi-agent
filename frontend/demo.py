import os
import time

import httpx
import streamlit as st

API = os.environ.get("REPOPILOT_API_URL", "http://127.0.0.1:8000")
st.set_page_config(page_title="RepoPilot", page_icon="🛠️", layout="wide")
st.title("RepoPilot · 智能代码修复")
st.caption("LangGraph + MCP · 本地演示 · 修改保存在独立任务副本")


def api(method, path, **kwargs):
    response = httpx.request(method, API + path, timeout=15, **kwargs)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = response.json().get("detail") or response.reason_phrase
        except (ValueError, AttributeError):
            detail = response.reason_phrase
        raise ValueError(f"{str(detail)[:1000]}（HTTP {response.status_code}）") from exc
    return response.json()


with st.form("new_task"):
    issue = st.text_area("Bug 描述", "Token 过期时返回 500，预期返回 401；请修复并补充测试。")
    issue_url = st.text_input("可选 GitHub Issue URL（填写后从配置的远端仓库读取需求）")
    repository = st.text_input("本地仓库路径（必须位于后端配置的受控根目录内）", "demo_repository")
    mode = st.selectbox("运行模式", ["multi_full", "multi_no_review", "single"])
    retry_policy = st.selectbox("重试策略", ["后端默认", "继续当前副本", "每次尝试独立副本"])
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
                "retry_workspace_policy": {"后端默认": None, "继续当前副本": "preserve",
                                           "每次尝试独立副本": "isolated"}[retry_policy],
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
        if state.get("retry_workspace_policy") == "isolated" and state.get("candidate_id"):
            st.caption(f"独立候选第 {state['candidate_number']} 轮 · {state['candidate_id']}")
            with st.expander("此前尝试（现场保留）"):
                st.json(state.get("attempt_history", []))
        st.subheader("代码 Diff")
        st.code(diff["diff"] or "暂无修改", language="diff")
        st.download_button("下载补丁", diff["diff"], f"{task_id}.patch")
        with st.expander("计划、测试结果与审核", expanded=True):
            st.json(
                {
                    "plan": state["plan"],
                    "tests": state["test_results"],
                    "review": state["review_results"],
                    "regression_evidence": state.get("regression_results", []),
                }
            )
        with st.expander("Agent 日志和检索历史"):
            st.json(api("GET", f"/api/tasks/{task_id}/events"))
        if state.get("patch_transaction_version") == 1:
            recovery_key = "patch-recovery:" + task_id
            if st.button("检查补丁事务恢复"):
                st.session_state[recovery_key] = api("GET", f"/api/tasks/{task_id}/recovery/patch")
            recovery = st.session_state.get(recovery_key)
            if recovery and recovery["required"]:
                st.warning("存在未完成写入的补丁。核对文件摘要后显式恢复，再继续 Docker 验证。")
                st.json(recovery)
                if len(recovery["transactions"]) == 1:
                    item = recovery["transactions"][0]
                    if st.button("确认恢复这份补丁事务", disabled=not item["recoverable"]):
                        api("POST", f"/api/tasks/{task_id}/recovery/patch",
                            json={"journal_digest": item["journal_digest"]})
                        st.session_state.pop(recovery_key, None)
                        st.rerun()
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
                        json={"diff_digest": diff["diff_digest"],
                              "candidate_id": diff.get("candidate_id")},
                    )
                    st.rerun()
        elif state["execution_status"] == "approved":
            st.caption("发布分为预览、批准完整请求和创建草稿 PR；批准 Diff 不等于批准发布。")
            publication_key = "publication:" + task_id
            if st.button("预览或刷新草稿 PR 发布请求"):
                st.session_state[publication_key] = api(
                    "POST", f"/api/tasks/{task_id}/publication/preview", json={})
            publication = st.session_state.get(publication_key)
            if publication:
                plan = publication["plan"]
                st.write({"仓库": plan["target"]["repository"], "基分支": plan["base_branch"],
                          "基线提交": plan["base_sha"], "目录": plan["target"]["subdirectory"],
                          "新分支": plan["branch"], "标题": plan["title"]})
                st.text(plan["body"])
                st.caption("发布请求 SHA-256：" + publication["request_digest"])
                with st.expander("完整发布请求（含将要写入的文件）"):
                    st.json(plan)
                if st.button("批准这份完整发布请求"):
                    st.session_state[publication_key] = api(
                        "POST", f"/api/tasks/{task_id}/publication/approve",
                        json={"request_digest": publication["request_digest"]})
                    st.rerun()
                if st.button("创建已批准的 GitHub 草稿 PR",
                             disabled=publication["approval_status"] != "approved"):
                    published = api("POST", f"/api/tasks/{task_id}/pr", json={
                        "diff_digest": diff["diff_digest"], "candidate_id": diff.get("candidate_id"),
                        "publication_digest": publication["request_digest"]})
                    st.link_button("查看草稿 PR", published["url"])
        elif state["execution_status"] == "blocked":
            if st.button("Docker 就绪后继续测试"):
                api("POST", f"/api/tasks/{task_id}/resume")
                st.rerun()
        elif state["execution_status"] == "retryable":
            failure = state.get("failure") or {}
            remaining = max(0, int(failure.get("retry_at", 0) - time.time()) + 1)
            st.warning(
                f"模型暂时不可用（{failure.get('kind', 'unknown')}）。"
                f"冷却剩余 {remaining} 秒；已手动重试 {state.get('provider_retry_count', 0)} 次。"
                "点击刷新更新冷却时间，随后可从失败节点继续；此前补丁和测试记录会保留。"
            )
            if st.button("冷却后重试模型请求", disabled=remaining > 0):
                api("POST", f"/api/tasks/{task_id}/resume")
                st.rerun()
        elif state["execution_status"] in {"queued", "running"}:
            st.info("若服务曾中断，可刷新确认状态后从已保存节点继续。执行中的任务受锁保护。")
            if st.button("从已保存节点继续"):
                api("POST", f"/api/tasks/{task_id}/resume")
                st.rerun()
        elif state["execution_status"] in {"creating", "creation_failed"}:
            st.info("任务副本尚未准备完成，已有现场保留；可在访问恢复后继续准备。")
            if st.button("继续准备任务副本"):
                api("POST", f"/api/tasks/{task_id}/resume")
                st.rerun()
        elif state["execution_status"] == "failed":
            st.info("任务已终止。检查错误、日志与补丁后创建新任务；此任务不会自动重试或发布。")
except (httpx.HTTPError, ValueError) as exc:
    st.error(f"API 请求失败：{exc}")
