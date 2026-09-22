import { post } from "./api.js";
import { state } from "./store.js";
import { $, closeDialog, esc, icon, openDialog, toast } from "./ui.js";

let formMode = "create";
let activeGroupId = "";
let renameTarget = null;

const allClients = () => state.zones.flatMap(group => group.clients.map(client => ({ ...client, groupId: group.id, groupName: group.name })));
const groupById = id => state.zones.find(group => group.id === id);

function locked(button, active, label = "处理中") {
  button.disabled = active;
  button.setAttribute("aria-busy", String(active));
  button.classList.toggle("is-pending", active);
  if (active) {
    button.dataset.label = button.innerHTML;
    button.textContent = label;
  } else if (button.dataset.label) {
    button.innerHTML = button.dataset.label;
    delete button.dataset.label;
  }
}

async function submit(endpoint, payload, button) {
  locked(button, true);
  try {
    await post(endpoint, payload);
    document.dispatchEvent(new CustomEvent("state-refresh"));
    toast("播放组已更新");
    return true;
  } catch (error) {
    if (error.details?.partialMutation) {
      document.dispatchEvent(new CustomEvent("state-refresh"));
      const rollback = error.details.rollbackErrors?.length ? `；回滚异常：${error.details.rollbackErrors.join("、")}` : "；已尝试恢复原分组";
      toast(`${error.message}${rollback}`, true, 8000);
    } else {
      toast(error.message, true, 5000);
    }
    return false;
  } finally {
    locked(button, false);
  }
}

export function renderGroupManager() {
  const root = $("#groupManager");
  if (!root) return;
  root.innerHTML = state.zones.map(group => `
    <article class="group-admin-row">
      <header><div><span class="group-status ${group.connectedCount ? "online" : ""}"></span><div><b>${esc(group.name)}</b><small>${group.clients.length} 台设备 · ${group.connectedCount} 在线</small></div></div><button class="icon-btn" data-group-rename="${esc(group.id)}" aria-label="重命名播放组">${icon("edit")}</button></header>
      <div class="group-admin-clients">${group.clients.map(client => `
        <button data-client-rename="${esc(client.id)}" class="admin-client ${client.connected ? "" : "offline"}">
          ${icon("speaker")}<span><b>${esc(client.name)}</b><small>${client.connected ? client.ip || "在线" : "离线"} · ${esc(group.name)}</small></span>${icon("edit")}
        </button>`).join("")}</div>
      <footer><button class="secondary-btn" data-group-members="${esc(group.id)}">${icon("network")}调整成员</button><button class="secondary-btn danger-quiet" data-group-merge="${esc(group.id)}" ${state.zones.length < 2 ? "disabled" : ""}>${icon("collapse")}合并此组</button></footer>
    </article>`).join("") || '<p class="empty">尚无已注册设备</p>';
}

function clientCheckboxes(selected = []) {
  const selectedSet = new Set(selected);
  return allClients().map(client => `
    <label class="client-choice ${client.connected ? "" : "offline"}">
      <input type="checkbox" value="${esc(client.id)}" ${selectedSet.has(client.id) ? "checked" : ""}>
      ${icon("speaker")}<span><b>${esc(client.name)}</b><small>${client.connected ? "在线" : "离线"} · ${esc(client.groupName)}</small></span>
    </label>`).join("");
}

function openGroupForm(mode, groupId = "") {
  formMode = mode;
  activeGroupId = groupId;
  const group = groupById(groupId);
  const creating = mode === "create";
  const merging = mode === "merge";
  $("#groupFormTitle").textContent = creating ? "新建播放组" : merging ? `合并“${group?.name || "播放组"}”` : `调整“${group?.name || "播放组"}”`;
  $("#groupNameField").hidden = !creating;
  $("#groupStreamField").hidden = !creating;
  $("#groupClientField").hidden = merging;
  $("#mergeTargetField").hidden = !merging;
  if (creating) {
    $("#groupNameInput").value = "新播放组";
    $("#groupStreamInput").innerHTML = state.sources.map(source => `<option value="${esc(source.id)}" ${source.id === "Default" ? "selected" : ""}>${esc(source.name || source.id)}</option>`).join("");
    $("#groupClientOptions").innerHTML = clientCheckboxes();
  } else if (!merging) {
    $("#groupClientOptions").innerHTML = clientCheckboxes(group.clients.map(client => client.id));
  } else {
    $("#mergeTargetInput").innerHTML = state.zones.filter(item => item.id !== groupId).map(item => `<option value="${esc(item.id)}">${esc(item.name)} · ${item.clients.length} 台</option>`).join("");
  }
  openDialog("#groupFormDialog");
}

function openRename(type, id) {
  const client = allClients().find(item => item.id === id);
  const group = groupById(id);
  renameTarget = { type, id };
  $("#nameTitle").textContent = type === "client" ? "重命名设备" : "重命名播放组";
  $("#nameInput").value = type === "client" ? client?.name || "" : group?.name || "";
  openDialog("#nameDialog");
  $("#nameInput").select();
}

export function initGroups() {
  $("#manageGroups").onclick = () => { renderGroupManager(); openDialog("#groupsDialog"); };
  $("#createGroupButton").onclick = () => openGroupForm("create");
  $("#groupManager").onclick = event => {
    const renameGroup = event.target.closest("[data-group-rename]");
    const renameClient = event.target.closest("[data-client-rename]");
    const members = event.target.closest("[data-group-members]");
    const merge = event.target.closest("[data-group-merge]");
    if (renameGroup) openRename("group", renameGroup.dataset.groupRename);
    if (renameClient) openRename("client", renameClient.dataset.clientRename);
    if (members) openGroupForm("members", members.dataset.groupMembers);
    if (merge) openGroupForm("merge", merge.dataset.groupMerge);
  };
  $("#nameForm").onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter;
    const client = renameTarget.type === "client";
    const ok = await submit(client ? "/api/snapcast/client-name" : "/api/snapcast/group-name", client ? { clientId: renameTarget.id, name: $("#nameInput").value } : { groupId: renameTarget.id, name: $("#nameInput").value }, button);
    if (ok) closeDialog("#nameDialog");
  };
  $("#groupForm").onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter;
    let endpoint, payload;
    if (formMode === "merge") {
      endpoint = "/api/snapcast/group-merge";
      payload = { sourceGroupId: activeGroupId, targetGroupId: $("#mergeTargetInput").value };
    } else {
      const clientIds = [...$("#groupClientOptions").querySelectorAll("input:checked")].map(input => input.value);
      if (!clientIds.length) return toast("请至少选择一台设备", true);
      endpoint = formMode === "create" ? "/api/snapcast/group-create" : "/api/snapcast/group-members";
      payload = formMode === "create" ? { name: $("#groupNameInput").value, clientIds, streamId: $("#groupStreamInput").value } : { groupId: activeGroupId, clientIds };
    }
    const ok = await submit(endpoint, payload, button);
    if (ok) closeDialog("#groupFormDialog");
  };
}
